# Paper trading — korak po korak

## Što radi

Paper trading koristi jedan trajni virtualni račun iz SQLite baze. Analizira cijelu
watchlistu, sprema odluke, radi zajednički plan ulaganja i tek na kasnijem runu
izvršava naloge po prvom tržišnom `Open` podatku nakon datuma odluke.

Ne spaja se na brokera i ne koristi pravi novac. Kada dokumentacija kaže da sustav
"skida novac", to znači da u virtualnom cash ledgeru zapisuje umanjenje salda.

```text
račun iz baze
  → izvrši ranije PENDING naloge na D+1 Open
  → vrednuje postojeće pozicije
  → analizira sve tickere
  → sprema Buy/Overweight/Hold/Underweight/Sell odluke
  → radi jednu portfolio alokaciju
  → sprema nove PENDING naloge
  → sprema dnevni snapshot i statistiku
```

Detaljne naredbe su u [uputama za pokretanje](persistent-paper-trading-usage.md),
a gotovi upiti u [SQL statistici](paper-trading-sql-queries.md).

## 1. Odabir Paper trading moda

Pokreni CLI i odaberi:

```text
Paper trading — analyze a watchlist and trade the virtual portfolio
```

Zatim unesi tickere odvojene zarezom, razmakom ili novim redom, primjerice:

```text
CCJ, UEC, DNN, NXE, UUUU, URG, EU, UROY, LEU, AEC, ISOU
```

CLI validira, normalizira i uklanja duplikate. Postavke datuma, analitičara,
modela i research deptha biraš jednom za cijelu watchlistu.

## 2. Račun se učitava iz nove baze

V2 baza je po defaultu `db/paper_trading_v2.sqlite`. Račun se traži po nazivu iz
`TRADINGAGENTS_PAPER_ACCOUNT`. Ako ne postoji, prvi Paper run ga stvara i jednom
knjiži `TRADINGAGENTS_PAPER_INITIAL_CASH`.

```text
Account: default
Cash ledger: INITIAL_FUNDING +$1,000
Cash balance: $1,000
Positions: none
```

Svaki idući run čita isti ledger i iste pozicije. Promjena initial-cash varijable
ne mijenja postojeći račun.

## 3. Najprije se izvršavaju stari pending nalozi

Odluka od `2026-01-02` ne koristi closing cijenu kao lažno izvršenje. Nalog ostaje
`PENDING`, a run s kasnijim datumom traži prvi valjani tržišni `Open` nakon
`2026-01-02` i najkasnije na novi datum.

```text
2026-01-02  CCJ Buy → PENDING BUY $20
2026-01-05  prvi idući market Open → FILLED
```

Na cijenu se primjenjuje konfigurirani slippage. Sve prodaje izvršavaju se prije
kupnji. Ako nedostaje cijena za ijedan nalog u istom planu, cijeli plan ostaje
pending kako djelomično izvršenje ne bi promijenilo alokaciju.

Izvršenje i promjena salda odvijaju se u jednoj bazičnoj transakciji. Ponovljeni
run ne može dvaput izvršiti isti order.

## 4. Cash ledger stvarno umanjuje virtualni saldo

Za virtualnu kupnju od `$20` nastaju povezani zapisi:

```text
orders       PENDING → FILLED
fills        količina, Open cijena, slippage, notional
cash_ledger  BUY -$20
positions    nova količina i prosječna cijena
```

Kod prodaje `cash_ledger` dobiva pozitivan `SELL` zapis, pozicija se smanjuje ili
zatvara, a fill sprema realized P&L. Ledger je append-only: postojeći redovi ne
mogu se mijenjati ni brisati.

## 5. Postojeće pozicije vrednuju se prije nove odluke

Za svaki otvoreni ticker sustav uzima zadnji valjani `Close` na datum runa ili
prije njega. Time dobiva market value, unrealized P&L i equity. Isto se pokušava
napraviti za benchmark, defaultno `URA`.

## 6. Svi tickeri prvo prolaze punu analizu

Za svaki ticker zasebno se izvršava:

```text
Analyst Team → Bull/Bear → Research Manager → Trader
  → Risk debate → Portfolio Manager
```

Iz završnog teksta izvlači se `Buy`, `Overweight`, `Hold`, `Underweight` ili
`Sell`. Odluka, cijena na datum odluke, putanja i hash izvještaja te eventualna
greška spremaju se u `decisions`. Ako se run prekine, već dovršeni tickeri ostaju
u bazi i resume ih ne analizira ponovno.

## 7. Tek nakon svih analiza nastaje zajednički plan

Alokator je deterministički i ne ovisi o redoslijedu watchliste. Prvo planira
prodaje, zatim hold, pa kupnje. Defaultna pravila su:

| Ocjena | Plan |
|---|---|
| `Buy` | kupnja do `$20` |
| `Overweight` | kupnja do `$10` |
| `Hold` | bez naloga |
| `Underweight` | prodaja polovice otvorene količine |
| `Sell` | prodaja cijele otvorene količine |

Svaka kupnja dodatno poštuje maksimalnih `20%` equityja po tickeru i cash rezervu
od `10%`. Ako pravilo blokira trgovinu, order se sprema kao `NOOP` ili `REJECTED`
s razlogom. Planirani order se sprema kao `PENDING`.

## 8. Dnevni snapshot čuva rezultat kroz vrijeme

Na kraju runa baza sprema cash, market value, total equity, realized i unrealized
P&L, net contributions, benchmark te stanje svake pozicije. Jedan account ima
najviše jedan snapshot i jedan `daily:<datum>` run po datumu, pa retry ne može
stvoriti dvostruke naloge.

## 9. Što dobivaš nakon više dana

Iz iste baze možeš rekonstruirati:

- svaku LLM odluku i pripadajući report;
- svaki planirani, odbijeni i izvršeni nalog;
- svaku virtualnu promjenu casha;
- trenutačne pozicije;
- koliko je kupljeno i prodano po tickeru;
- realized, unrealized i total P&L;
- dnevnu equity krivulju, return i max drawdown;
- usporedbu s benchmarkom.

## 10. Gdje se što sprema

```text
db/paper_trading_v2.sqlite   account, ledger, odluke, nalozi i statistika
reports/                     Markdown izvještaji svake analize
exports/                     CSV/JSON izvozi
```

Legacy `db/portfolio.sqlite` ostaje netaknut i v2 ga ne koristi.
