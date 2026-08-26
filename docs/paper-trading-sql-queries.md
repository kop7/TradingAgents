# SQL upiti za Paper trading statistiku

Primjeri koriste account `uranium-test`. Zamijeni ga svojim nazivom. Novac je u
bazi spremljen kao micro-dollar (`/ 1,000,000`), a količina kao nano-share
(`/ 1,000,000,000`).

```bash
sqlite3 -header -column db/paper_trading_v2.sqlite
```

## Account i trenutačni cash

```sql
SELECT a.id, a.name, a.currency, a.status,
       ROUND(b.cash_micros / 1000000.0, 2) AS cash,
       a.benchmark_symbol, a.strategy_version
FROM accounts a
JOIN account_balances b ON b.account_id = a.id
WHERE a.name = 'uranium-test';
```

## Cijeli cash ledger

```sql
SELECT l.occurred_at, l.entry_type,
       ROUND(l.amount_micros / 1000000.0, 2) AS amount,
       ROUND(l.balance_after_micros / 1000000.0, 2) AS balance_after,
       l.fill_id, l.note
FROM cash_ledger l
JOIN accounts a ON a.id = l.account_id
WHERE a.name = 'uranium-test'
ORDER BY l.occurred_at, l.id;
```

## Otvorene pozicije

```sql
SELECT p.symbol,
       ROUND(p.quantity_nanos / 1000000000.0, 6) AS quantity,
       ROUND(p.average_cost_micros / 1000000.0, 4) AS average_cost,
       ROUND(p.last_price_micros / 1000000.0, 4) AS last_price,
       ROUND(p.quantity_nanos * p.last_price_micros /
             1000000000000000.0, 2) AS market_value,
       p.last_price_as_of
FROM account_positions p
JOIN accounts a ON a.id = p.account_id
WHERE a.name = 'uranium-test'
ORDER BY p.symbol;
```

## Sve kupnje i prodaje

```sql
SELECT f.executed_at, f.symbol, d.rating, f.side,
       ROUND(f.quantity_nanos / 1000000000.0, 6) AS quantity,
       ROUND(f.effective_price_micros / 1000000.0, 4) AS fill_price,
       ROUND(f.gross_notional_micros / 1000000.0, 2) AS notional,
       ROUND(f.fee_micros / 1000000.0, 2) AS fee,
       ROUND(f.realized_pnl_micros / 1000000.0, 2) AS realized_pnl
FROM fills f
JOIN accounts a ON a.id = f.account_id
JOIN orders o ON o.id = f.order_id
JOIN decisions d ON d.id = o.decision_id
WHERE a.name = 'uranium-test'
ORDER BY f.executed_at, f.id;
```

## Pending, NOOP i odbijeni nalozi

```sql
SELECT d.analysis_date, o.symbol, d.rating, o.side, o.status,
       ROUND(o.requested_notional_micros / 1000000.0, 2) AS requested_cash,
       ROUND(o.requested_quantity_nanos / 1000000000.0, 6)
         AS requested_quantity,
       o.reason
FROM orders o
JOIN accounts a ON a.id = o.account_id
JOIN decisions d ON d.id = o.decision_id
WHERE a.name = 'uranium-test'
  AND o.status IN ('PENDING', 'REJECTED', 'NOOP')
ORDER BY d.analysis_date, o.symbol;
```

## Koliko je kupljeno i prodano po tickeru

```sql
SELECT f.symbol,
       SUM(f.side = 'BUY') AS buy_count,
       SUM(f.side = 'SELL') AS sell_count,
       ROUND(SUM(CASE WHEN f.side = 'BUY'
                      THEN f.gross_notional_micros ELSE 0 END) /
             1000000.0, 2) AS total_bought,
       ROUND(SUM(CASE WHEN f.side = 'SELL'
                      THEN f.gross_notional_micros ELSE 0 END) /
             1000000.0, 2) AS total_sold,
       ROUND(SUM(f.realized_pnl_micros) / 1000000.0, 2) AS realized_pnl
FROM fills f
JOIN accounts a ON a.id = f.account_id
WHERE a.name = 'uranium-test'
GROUP BY f.symbol
ORDER BY realized_pnl DESC, f.symbol;
```

## Dnevna equity krivulja i benchmark

```sql
SELECT s.snapshot_date,
       ROUND(s.cash_micros / 1000000.0, 2) AS cash,
       ROUND(s.market_value_micros / 1000000.0, 2) AS positions,
       ROUND(s.total_equity_micros / 1000000.0, 2) AS equity,
       ROUND(s.realized_pnl_micros / 1000000.0, 2) AS realized_pnl,
       ROUND(s.unrealized_pnl_micros / 1000000.0, 2) AS unrealized_pnl,
       ROUND(s.benchmark_value_micros / 1000000.0, 2) AS benchmark_value
FROM portfolio_daily_snapshots s
JOIN accounts a ON a.id = s.account_id
WHERE a.name = 'uranium-test'
ORDER BY s.snapshot_date;
```

## Ukupan rezultat od prvog do zadnjeg snapshota

```sql
WITH curve AS (
  SELECT s.*,
         FIRST_VALUE(s.total_equity_micros) OVER (
           ORDER BY s.snapshot_date, s.id
         ) AS start_equity,
         FIRST_VALUE(s.benchmark_value_micros) OVER (
           ORDER BY s.snapshot_date, s.id
         ) AS start_benchmark
  FROM portfolio_daily_snapshots s
  JOIN accounts a ON a.id = s.account_id
  WHERE a.name = 'uranium-test'
), latest AS (
  SELECT * FROM curve ORDER BY snapshot_date DESC, id DESC LIMIT 1
)
SELECT snapshot_date AS end_date,
       ROUND(total_equity_micros / 1000000.0, 2) AS ending_equity,
       ROUND((total_equity_micros * 1.0 / start_equity - 1) * 100, 2)
         AS portfolio_return_pct,
       ROUND((benchmark_value_micros * 1.0 / start_benchmark - 1) * 100, 2)
         AS benchmark_return_pct,
       ROUND(realized_pnl_micros / 1000000.0, 2) AS realized_pnl,
       ROUND(unrealized_pnl_micros / 1000000.0, 2) AS unrealized_pnl
FROM latest;
```

## Maksimalni drawdown

```sql
WITH equity AS (
  SELECT s.snapshot_date, s.total_equity_micros,
         MAX(s.total_equity_micros) OVER (
           ORDER BY s.snapshot_date, s.id ROWS UNBOUNDED PRECEDING
         ) AS peak_equity
  FROM portfolio_daily_snapshots s
  JOIN accounts a ON a.id = s.account_id
  WHERE a.name = 'uranium-test'
), drawdowns AS (
  SELECT snapshot_date,
         (total_equity_micros * 1.0 / peak_equity - 1) * 100 AS drawdown_pct
  FROM equity
)
SELECT snapshot_date, ROUND(drawdown_pct, 2) AS max_drawdown_pct
FROM drawdowns
ORDER BY drawdown_pct
LIMIT 1;
```

## Odluke nasuprot izvršenju

```sql
SELECT d.analysis_date, d.symbol, d.rating,
       d.status AS decision_status, o.status AS order_status, o.side,
       f.executed_at,
       ROUND(f.gross_notional_micros / 1000000.0, 2) AS filled_notional,
       d.report_path
FROM decisions d
JOIN analysis_runs r ON r.id = d.run_id
JOIN accounts a ON a.id = r.account_id
LEFT JOIN orders o ON o.decision_id = d.id
LEFT JOIN fills f ON f.order_id = o.id
WHERE a.name = 'uranium-test'
ORDER BY d.analysis_date, d.symbol;
```

## Zdravlje dnevnih runova

```sql
SELECT r.analysis_date, r.run_key, r.status,
       COUNT(d.id) AS decisions,
       SUM(d.status = 'FAILED') AS failed_decisions,
       SUM(o.status = 'PENDING') AS pending_orders,
       r.started_at, r.completed_at, r.error_text
FROM analysis_runs r
JOIN accounts a ON a.id = r.account_id
LEFT JOIN decisions d ON d.run_id = r.id
LEFT JOIN orders o ON o.decision_id = d.id
WHERE a.name = 'uranium-test'
GROUP BY r.id
ORDER BY r.analysis_date;
```

