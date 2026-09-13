# Paper trading — MySQL statistika i operativni pregled

Vodič za **MySQL 8.0.16+**, shemu v3. Zamjenjuje ranije SQLite primjere.
Svi upiti čitaju podatke; `SET` mijenja samo varijable trenutne konekcije.
Prije korištenja pokreni `tradingagents db migrate`.

## 1. Parametri i tumačenje

U SQL klijentu odaberi bazu i izvrši ovaj blok. Ostale upite izvršavaj u istoj
konekciji. Prilagodi račun, razdoblje i ticker. Datumi su uključivi.

```sql
SET @account_name = 'uranium';
SET @account_id = (SELECT id FROM accounts WHERE name = @account_name);
SET @date_from = '2026-01-01';
SET @date_to = '2026-12-31';
SET @ticker = 'UEC';
SET @as_of = CURRENT_DATE();
SELECT @account_id AS account_id, @account_name AS account_name;
```

Ako je ID NULL, provjeri račun: `SELECT id, name FROM accounts;`.
Za povijesnu provjeru starosti promijeni `@as_of`. **Trenutačni** upiti koriste
zadnje stanje bez filtra razdoblja; povijesno stanje čita se iz snapshotova.

| Podatak | Značenje |
| --- | --- |
| `*_micros / 1000000.0` | Novac ili cijena |
| `quantity_nanos / 1000000000.0` | Broj dionica/jedinica |
| Cash | Saldo virtualnog ledgera; pending kupnje još nisu naplaćene |
| Equity | Cash + vrijednost otvorenih pozicija |
| Realizirani P&L | Rezultat prodanih količina prema prosječnoj nabavnoj cijeni |
| Nerealizirani P&L | Rezultat otvorenih količina prema spremljenoj cijeni |
| NULL | Nema podatka ili izračun nije definiran; nije nula |

Cijene nisu live. Količine se pretvaraju u decimalne jedinice prije množenja
da se izbjegne BIGINT overflow. Sustav ne radi konverziju valuta: ne zbrajaj
različite valute niti pretpostavljaj da oznaka računa pretvara strane kotacije.

## 2. Svi računi i svježina podataka

Trenutačni cash prikazan je odvojeno od zadnjeg povijesnog snapshota.

```sql
WITH latest AS (
 SELECT s.*, ROW_NUMBER() OVER (PARTITION BY account_id
   ORDER BY snapshot_date DESC, id DESC) AS rn
 FROM portfolio_daily_snapshots s
)
SELECT a.id, a.name, a.status, a.currency, a.benchmark_symbol,
 ROUND(b.cash_micros / 1000000.0, 2) AS current_cash,
 s.snapshot_date, DATEDIFF(@as_of, s.snapshot_date) AS snapshot_age_days,
 ROUND(s.total_equity_micros / 1000000.0, 2) AS snapshot_equity,
 ROUND((s.total_equity_micros - s.net_contributions_micros) / 1000000.0, 2)
   AS snapshot_pnl_after_cash_flows,
 a.strategy_version, a.strategy_config_json
FROM accounts a JOIN account_balances b ON b.account_id = a.id
LEFT JOIN latest s ON s.account_id = a.id AND s.rn = 1
ORDER BY a.name;
```

P&L nakon cash tokova uključuje naknade i eventualne cash korekcije. Uspoređuj
račune uz isti period, kapital, valutu i strategiju, ne samo apsolutnu dobit.

## 3. Cash, otvorene pozicije i obveze — trenutačno

```sql
WITH positions AS (
 SELECT COALESCE(SUM(quantity_nanos / 1000000000.0 * last_price_micros / 1000000.0), 0) AS value
 FROM account_positions WHERE account_id = @account_id
), pending AS (
 SELECT COUNT(*) AS buys,
 COALESCE(SUM(requested_notional_micros / 1000000.0), 0) AS notional
 FROM orders WHERE account_id = @account_id AND status = 'PENDING' AND side = 'BUY'
)
SELECT ROUND(b.cash_micros / 1000000.0, 2) AS cash,
 ROUND(p.value, 2) AS position_value,
 ROUND(b.cash_micros / 1000000.0 + p.value, 2) AS equity,
 ROUND(100 * (b.cash_micros / 1000000.0) /
   NULLIF(b.cash_micros / 1000000.0 + p.value, 0), 2) AS cash_pct,
 q.buys AS pending_buys, ROUND(q.notional, 2) AS pending_buy_notional,
 ROUND(b.cash_micros / 1000000.0 - q.notional, 2) AS cash_less_pending_buys
FROM account_balances b CROSS JOIN positions p CROSS JOIN pending q
WHERE b.account_id = @account_id;
```

Posljednja kolona nije zajamčeni budući saldo: ne uključuje pending prodaje,
naknade ni odbijanje naloga. Pending obveze još nisu rezervacija u ledgeru.

## 4. Pozicije, koncentracija i otvoreni gubici — trenutačno

```sql
WITH positions AS (
 SELECT p.*, quantity_nanos / 1000000000.0 AS qty,
 average_cost_micros / 1000000.0 AS cost, last_price_micros / 1000000.0 AS price
 FROM account_positions p WHERE account_id = @account_id
), totals AS (SELECT COALESCE(SUM(qty * price), 0) AS invested FROM positions)
SELECT p.symbol, ROUND(qty, 8) AS quantity, cost, price,
 ROUND(qty * price, 2) AS market_value,
 ROUND(qty * (price - cost), 2) AS unrealized_pnl,
 ROUND(100 * (price / NULLIF(cost, 0) - 1), 2) AS unrealized_return_pct,
 ROUND(100 * qty * price / NULLIF(t.invested + b.cash_micros / 1000000.0, 0), 2)
   AS weight_of_equity_pct,
 p.last_price_as_of, DATEDIFF(@as_of, p.last_price_as_of) AS price_age_days,
 i.status AS ticker_status, i.paper_enabled
FROM positions p CROSS JOIN totals t
JOIN account_balances b ON b.account_id = @account_id
LEFT JOIN instruments i ON i.symbol = p.symbol
ORDER BY market_value DESC;
```

Starost je u kalendarskim danima; vikendi/praznici nisu automatski greška.
Isključivanje tickera iz watchliste ne zatvara već otvorenu poziciju.

## 5. Equity krivulja, rezultat intervala i uplate

```sql
WITH history AS (
 SELECT s.*, LAG(total_equity_micros) OVER (ORDER BY snapshot_date, id) AS prev_equity,
 LAG(net_contributions_micros) OVER (ORDER BY snapshot_date, id) AS prev_flows,
 LAG(snapshot_date) OVER (ORDER BY snapshot_date, id) AS prev_date
 FROM portfolio_daily_snapshots s
 WHERE account_id = @account_id AND snapshot_date <= @date_to
)
SELECT snapshot_date, prev_date, DATEDIFF(snapshot_date, prev_date) AS gap_days,
 ROUND(total_equity_micros / 1000000.0, 2) AS equity,
 ROUND((net_contributions_micros - prev_flows) / 1000000.0, 2) AS external_flow,
 ROUND((total_equity_micros - prev_equity -
   (net_contributions_micros - prev_flows)) / 1000000.0, 2) AS interval_pnl,
 ROUND(100 * (total_equity_micros - prev_equity -
   (net_contributions_micros - prev_flows)) / NULLIF(prev_equity, 0), 4) AS interval_return_pct,
 ROUND(realized_pnl_micros / 1000000.0, 2) AS cumulative_realized_pnl,
 ROUND(unrealized_pnl_micros / 1000000.0, 2) AS unrealized_pnl,
 ROUND(benchmark_value_micros / 1000000.0, 2) AS benchmark_value
FROM history WHERE snapshot_date >= @date_from ORDER BY snapshot_date;
```

Prvi snapshot bez prethodnog podatka nema izračun prinosa. Ako postoje rupe,
prinos je između dva dostupna snapshota, ne jednodnevni prinos. Prilagodba uplata
pretpostavlja tok na kraju intervala, kao postojeći modul statistike. Za precizan
prinos uz intradnevne tokove trebaju dodatna vrednovanja. Realizirani P&L je
kumulativan, ne samo za prikazani dan; equity već uključuje naknade.

## 6. Kumulativni prinos i drawdown prilagođen cash tokovima

Računanje kreće od prvog snapshota, baza je 100. `@date_from` filtrira samo
prikaz: drawdown zadržava vrhunac koji je možda nastao prije odabranog razdoblja.

```sql
WITH history AS (
 SELECT s.*, LAG(total_equity_micros) OVER (ORDER BY snapshot_date, id) AS prev_equity,
 LAG(net_contributions_micros) OVER (ORDER BY snapshot_date, id) AS prev_flows
 FROM portfolio_daily_snapshots s
 WHERE account_id = @account_id AND snapshot_date <= @date_to
), factors AS (
 SELECT *, CASE WHEN prev_equity IS NULL THEN 1.0 WHEN prev_equity > 0 THEN
 (total_equity_micros - (net_contributions_micros - prev_flows)) / prev_equity END AS factor
 FROM history
), growth AS (
 SELECT *, SUM(CASE WHEN factor IS NULL OR factor <= 0 THEN 1 ELSE 0 END)
   OVER (ORDER BY snapshot_date, id) AS invalid_intervals,
 EXP(SUM(LN(CASE WHEN factor > 0 THEN factor END))
   OVER (ORDER BY snapshot_date, id)) AS wealth
 FROM factors
), peaks AS (
 SELECT *, MAX(wealth) OVER (ORDER BY snapshot_date, id) AS peak FROM growth
)
SELECT snapshot_date,
 CASE WHEN invalid_intervals = 0 THEN ROUND(100 * wealth, 4) END AS wealth_index,
 CASE WHEN invalid_intervals = 0 THEN ROUND(100 * (wealth - 1), 4) END AS return_pct,
 CASE WHEN invalid_intervals = 0 THEN ROUND(100 * (wealth / peak - 1), 4) END AS drawdown_pct,
 invalid_intervals
FROM peaks WHERE snapshot_date >= @date_from ORDER BY snapshot_date;
```

Najnegativniji drawdown je maksimalni pad u prikazu prema povijesnom vrhuncu.
Posljednji red daje zadnji drawdown. Uz nulti/negativni faktor ili nevaljanu bazu
izračun vraća NULL: logaritamsko ulančavanje ne opisuje potpuni gubitak kapitala.
Prinos počinje na prvom snapshotu, ne nužno na trenutku početne uplate.

## 7. Usporedba s benchmarkom na ista dva datuma

Jednostavni prinos vrijedi samo bez promjena neto uplata. Inače upit vraća NULL.

```sql
WITH sample AS (
 SELECT s.*, ROW_NUMBER() OVER (ORDER BY snapshot_date, id) AS first_row,
 ROW_NUMBER() OVER (ORDER BY snapshot_date DESC, id DESC) AS last_row
 FROM portfolio_daily_snapshots s
 WHERE account_id = @account_id AND snapshot_date BETWEEN @date_from AND @date_to
), limits AS (
 SELECT MIN(net_contributions_micros) AS min_flow,
 MAX(net_contributions_micros) AS max_flow, COUNT(*) AS observations FROM sample
)
SELECT f.snapshot_date AS start_date, l.snapshot_date AS end_date, n.observations,
 CASE WHEN n.min_flow = n.max_flow AND n.observations >= 2 THEN
 ROUND(100 * (l.total_equity_micros / NULLIF(f.total_equity_micros, 0) - 1), 3)
 END AS portfolio_return_pct,
 CASE WHEN n.min_flow = n.max_flow AND n.observations >= 2 THEN
 ROUND(100 * (l.benchmark_value_micros / NULLIF(f.benchmark_value_micros, 0) - 1), 3)
 END AS benchmark_return_pct,
 CASE WHEN n.min_flow = n.max_flow AND n.observations >= 2 THEN
 ROUND(100 * (l.total_equity_micros / NULLIF(f.total_equity_micros, 0) -
 l.benchmark_value_micros / NULLIF(f.benchmark_value_micros, 0)), 3)
 END AS excess_return_percentage_points
FROM sample f JOIN sample l ON l.last_row = 1 CROSS JOIN limits n
WHERE f.first_row = 1;
```

Razlika je u postotnim bodovima, nije regresijska alpha. Benchmark koristi
spremljene vrijednosti bez pretpostavke reinvestiranja dividendi. Neto snapshot
ne otkriva uplate i isplate koje se međusobno ponište unutar intervala; pregledaj ledger.

## 8. Win rate, profit factor i prosječna prodaja — razdoblje

```sql
SELECT COUNT(*) AS sell_fills, SUM(realized_pnl_micros > 0) AS winners,
 SUM(realized_pnl_micros < 0) AS losers, SUM(realized_pnl_micros = 0) AS breakeven,
 ROUND(100 * SUM(realized_pnl_micros > 0) / NULLIF(COUNT(*), 0), 2) AS win_rate_pct,
 ROUND(AVG(CASE WHEN realized_pnl_micros > 0 THEN realized_pnl_micros END) /
   1000000.0, 2) AS avg_winner,
 ROUND(AVG(CASE WHEN realized_pnl_micros < 0 THEN realized_pnl_micros END) /
   1000000.0, 2) AS avg_loser,
 ROUND(SUM(CASE WHEN realized_pnl_micros > 0 THEN realized_pnl_micros ELSE 0 END) /
 NULLIF(-SUM(CASE WHEN realized_pnl_micros < 0 THEN realized_pnl_micros ELSE 0 END), 0), 3)
   AS profit_factor,
 ROUND(AVG(realized_pnl_micros) / 1000000.0, 2) AS avg_pnl_per_sell
FROM fills WHERE account_id = @account_id AND side = 'SELL'
 AND DATE(executed_at) BETWEEN @date_from AND @date_to;
```

Jedinica je **prodajni fill**, uključujući djelomične prodaje, ne cijeli ciklus
ulaz–izlaz. Otvoreni gubitnici nisu uključeni. P&L uključuje efektivne cijene sa
slippageom, ali ne zasebne naknade. Bez gubitaka profit factor je NULL. Mali
broj prodaja nije dovoljan za stabilnu procjenu uspješnosti.

## 9. Rezultat po tickeru — realizirano u razdoblju

```sql
SELECT symbol, SUM(side = 'BUY') AS buys, SUM(side = 'SELL') AS sells,
 ROUND(SUM(CASE WHEN side = 'BUY' THEN gross_notional_micros ELSE 0 END) / 1000000.0, 2) AS bought,
 ROUND(SUM(CASE WHEN side = 'SELL' THEN gross_notional_micros ELSE 0 END) / 1000000.0, 2) AS sold,
 ROUND(SUM(realized_pnl_micros) / 1000000.0, 2) AS realized_pnl,
 ROUND(SUM(fee_micros) / 1000000.0, 2) AS fees_paid_in_period
FROM fills WHERE account_id = @account_id
 AND DATE(executed_at) BETWEEN @date_from AND @date_to
GROUP BY symbol ORDER BY realized_pnl DESC;
```

Kupljeno minus prodano nije dobit. Naknade kupnji mogu pripadati još otvorenim
pozicijama; nisu alocirane po zatvorenim lotovima. Usporedi s odjeljkom 4.

## 10. Izvršenja, slippage i pomak cijene nakon odluke

```sql
SELECT f.id, f.symbol, d.rating, d.analysis_date, f.executed_at, f.side,
 ROUND(f.quantity_nanos / 1000000000.0, 8) AS quantity,
 f.raw_price_micros / 1000000.0 AS market_open,
 f.effective_price_micros / 1000000.0 AS fill_price, f.fee_micros / 1000000.0 AS fee,
 ROUND((CASE WHEN f.side = 'BUY' THEN f.effective_price_micros - f.raw_price_micros
 ELSE f.raw_price_micros - f.effective_price_micros END) / 1000000.0 *
 (f.quantity_nanos / 1000000000.0), 4) AS modeled_slippage_cost,
 ROUND(100 * (f.raw_price_micros / NULLIF(d.reference_price_micros, 0) - 1), 3)
   AS market_move_since_decision_pct,
 DATEDIFF(DATE(f.executed_at), d.analysis_date) AS decision_to_fill_calendar_days
FROM fills f JOIN orders o ON o.id = f.order_id JOIN decisions d ON d.id = o.decision_id
WHERE f.account_id = @account_id AND DATE(f.executed_at) BETWEEN @date_from AND @date_to
ORDER BY f.executed_at, f.id;
```

Slippage je simulirana postavka, ne mjerenje brokera. Pomak Close→Open je zaseban.
Slippage je već uključen u equity/P&L: ne oduzimaj ga ponovno. Vrijeme izvršenja
je simulirano i nije podatak za mjerenje latencije brokera.

## 11. Pending, odbijeni i neaktivni nalozi — trenutačno

```sql
SELECT o.id, o.symbol, d.rating, o.side, o.status, d.analysis_date,
 DATEDIFF(@as_of, d.analysis_date) AS calendar_days_since_decision,
 o.requested_notional_micros / 1000000.0 AS requested_notional,
 o.requested_quantity_nanos / 1000000000.0 AS requested_quantity,
 o.reason, o.created_at, o.updated_at
FROM orders o JOIN decisions d ON d.id = o.decision_id
WHERE o.account_id = @account_id AND o.status IN ('PENDING', 'REJECTED', 'NOOP', 'CANCELLED')
ORDER BY o.status, d.analysis_date, o.symbol;
```

PENDING čeka idući raspoloživi Open nakon odluke i kasnije pokretanje aplikacije.
NOOP je namjerna odluka bez trgovanja. Uzrok je u `reason`. Broj kalendarskih dana
ne razlikuje praznike od tehničkog zastoja.

## 12. Analiza → nalog → izvršenje za ticker

```sql
SELECT r.id AS run_id, d.id AS decision_id, d.analysis_date, d.symbol,
 d.status AS analysis_status, d.rating, d.price_as_of,
 d.reference_price_micros / 1000000.0 AS reference_price,
 o.id AS order_id, o.status AS order_status, o.reason,
 f.id AS fill_id, f.executed_at, f.realized_pnl_micros / 1000000.0 AS realized_pnl,
 d.error_text, d.report_path, d.raw_decision_text
FROM decisions d JOIN analysis_runs r ON r.id = d.run_id
LEFT JOIN orders o ON o.decision_id = d.id LEFT JOIN fills f ON f.order_id = o.id
WHERE r.account_id = @account_id AND d.symbol = @ticker
 AND d.analysis_date BETWEEN @date_from AND @date_to
ORDER BY d.analysis_date DESC, d.id DESC;
```

`raw_decision_text` je finalna odluka, a kompletan izvještaj je u datoteci na
`report_path`. Dobit prodaje ne pripisuj samo SELL signalu: ovisi o ranijim kupnjama.

## 13. Zdravlje runova i pokrivenost tickera

```sql
SELECT r.id, r.analysis_date, r.status, JSON_LENGTH(r.requested_symbols_json) AS requested,
 COUNT(d.id) AS stored_decisions, COALESCE(SUM(d.status = 'COMPLETED'), 0) AS successful,
 COALESCE(SUM(d.status = 'FAILED'), 0) AS failed,
 JSON_LENGTH(r.requested_symbols_json) - COUNT(d.id) AS missing,
 r.started_at, r.completed_at, r.error_text
FROM analysis_runs r LEFT JOIN decisions d ON d.run_id = r.id
WHERE r.account_id = @account_id AND r.analysis_date BETWEEN @date_from AND @date_to
GROUP BY r.id ORDER BY r.analysis_date DESC, r.id DESC;
```

```sql
SELECT i.symbol, i.status, i.paper_enabled,
 MAX(CASE WHEN d.status = 'COMPLETED' THEN d.analysis_date END) AS last_success_in_period,
 COUNT(d.id) AS analyses_in_period, COALESCE(SUM(d.status = 'FAILED'), 0) AS failures_in_period
FROM instruments i LEFT JOIN (
 SELECT d.* FROM decisions d JOIN analysis_runs r ON r.id = d.run_id
 WHERE r.account_id = @account_id AND d.analysis_date BETWEEN @date_from AND @date_to
) d ON d.instrument_id = i.id
GROUP BY i.id ORDER BY last_success_in_period, i.symbol;
```

NULL znači da nema uspješne analize u razdoblju za taj račun. Broj pokušaja nije
dostupan: ponovno spremanje iste odluke ažurira zapis, ne stvara povijest pokušaja.

## 14. Raspodjela signala i razlozi odbijanja

```sql
SELECT d.rating, COUNT(*) AS completed_analyses,
 COALESCE(SUM(o.status = 'FILLED'), 0) AS filled,
 COALESCE(SUM(o.status = 'PENDING'), 0) AS pending,
 COALESCE(SUM(o.status = 'NOOP'), 0) AS noop,
 COALESCE(SUM(o.status = 'REJECTED'), 0) AS rejected, SUM(o.id IS NULL) AS without_order
FROM decisions d JOIN analysis_runs r ON r.id = d.run_id
LEFT JOIN orders o ON o.decision_id = d.id
WHERE r.account_id = @account_id AND d.status = 'COMPLETED'
 AND d.analysis_date BETWEEN @date_from AND @date_to
GROUP BY d.rating ORDER BY completed_analyses DESC;
```

```sql
SELECT o.status, o.reason, COUNT(*) AS occurrences
FROM orders o JOIN decisions d ON d.id = o.decision_id
WHERE o.account_id = @account_id AND d.analysis_date BETWEEN @date_from AND @date_to
 AND o.status IN ('NOOP', 'REJECTED', 'CANCELLED')
GROUP BY o.status, o.reason ORDER BY occurrences DESC;
```

## 15. Ledger i kontrola integriteta

```sql
SELECT id, occurred_at, entry_type, amount_micros / 1000000.0 AS amount,
 balance_after_micros / 1000000.0 AS balance_after, fill_id, note
FROM cash_ledger WHERE account_id = @account_id
 AND DATE(occurred_at) BETWEEN @date_from AND @date_to ORDER BY id;
```

Sljedeća tri upita trebaju vratiti prazne rezultate. Anomalije istraži po ID-u;
nemoj automatski prepisivati financijsku povijest.

```sql
WITH ledger AS (
 SELECT id, amount_micros, balance_after_micros,
 SUM(amount_micros) OVER (ORDER BY id ROWS UNBOUNDED PRECEDING) AS calculated
 FROM cash_ledger WHERE account_id = @account_id
)
SELECT * FROM ledger WHERE balance_after_micros <> calculated;
```

```sql
SELECT o.id, o.symbol, o.status, f.id AS fill_id, d.analysis_date, f.executed_at
FROM orders o JOIN decisions d ON d.id = o.decision_id
LEFT JOIN fills f ON f.order_id = o.id
WHERE o.account_id = @account_id AND (
 (o.status = 'FILLED' AND f.id IS NULL) OR (f.id IS NOT NULL AND o.status <> 'FILLED') OR
 (f.id IS NOT NULL AND DATE(f.executed_at) <= d.analysis_date));
```

```sql
SELECT id, snapshot_date, total_equity_micros, cash_micros, market_value_micros
FROM portfolio_daily_snapshots WHERE account_id = @account_id
 AND total_equity_micros <> cash_micros + market_value_micros;
```

Provjera datuma otkriva prerano izvršenje, ali ne dokazuje da je odabran baš prvi
raspoloživi Open; za to trebaju tržišni podaci i burzovni kalendar.

## 16. Redoslijed dnevnog pregleda i granice podataka

1. Svježina snapshotova i cijena (2 i 4).
2. Cash, pending obveze i koncentracija (3–4).
3. Prinos uz cash tokove, drawdown i benchmark (5–7).
4. Realizirani dobici nasuprot otvorenim gubicima (4 i 8–9).
5. Troškovi i neriješeni nalozi (10–11).
6. Odluke, izvještaji, greške i ledger (12–15).

Za pouzdanu betu, Sharpe/Sortino, sektorske korelacije, MAE/MFE, trajanje lotova
ili uspjeh svakog BUY signala nakon fiksnog horizonta trebaju dodatni podaci:
potpune pravilno uzorkovane serije, kalendar, korporativne akcije, lotovi i/ili
definirana bezrizična stopa. Rijetki snapshotovi nisu dovoljni; vodič ne izmišlja
takve metrike. Postojeći `paper stats` i `paper export` korisni su za izvoz, ali
kod usporedbe provjeri razdoblje i definiciju metrike, posebno tretman naknada.
