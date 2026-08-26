"""Persistence API for accounts, decisions, orders, fills, and snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from tradingagents.paper.database import PaperDatabase
from tradingagents.paper.models import Account, AnalysisRun, Decision, Fill, Order, Position
from tradingagents.paper.money import (
    as_decimal,
    micros_to_money,
    money_to_micros,
    notional_micros,
    quantity_to_nanos,
    signed_notional_micros,
    weighted_price_micros,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_symbol(symbol: str) -> str:
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    return normalize_symbol(symbol)


def _row(record_type, row):
    return record_type(**dict(row)) if row is not None else None


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class PaperRepository:
    def __init__(self, database: PaperDatabase | str | Path):
        self.database = database if isinstance(database, PaperDatabase) else PaperDatabase(database)
        self.database.initialize()

    def connect(self):
        return self.database.connect()

    def create_account(
        self,
        name: str,
        initial_cash,
        *,
        currency: str = "USD",
        strategy_version: str = "fixed-notional-v1",
        strategy_config: Mapping | None = None,
        benchmark_symbol: str = "URA",
    ) -> Account:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("account name must not be empty")
        funding = money_to_micros(initial_cash, field="initial_cash")
        if funding <= 0:
            raise ValueError("initial_cash must be greater than zero")
        now = _now()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM accounts WHERE name = ?", (normalized_name,)
            ).fetchone()
            if existing is not None:
                return _row(Account, existing)
            cursor = connection.execute(
                """INSERT INTO accounts
                   (name, currency, status, strategy_version, strategy_config_json,
                    benchmark_symbol, created_at, updated_at)
                   VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, ?)""",
                (
                    normalized_name,
                    currency.strip().upper() or "USD",
                    strategy_version,
                    _json(strategy_config or {}),
                    _canonical_symbol(benchmark_symbol),
                    now,
                    now,
                ),
            )
            account_id = int(cursor.lastrowid)
            connection.execute(
                """INSERT INTO cash_ledger
                   (account_id, entry_type, amount_micros, balance_after_micros,
                    idempotency_key, note, occurred_at)
                   VALUES (?, 'INITIAL_FUNDING', ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    funding,
                    funding,
                    f"account:{account_id}:initial-funding",
                    "Initial virtual account funding",
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _row(Account, row)

    def get_account(self, account: int | str) -> Account:
        field = "id" if isinstance(account, int) or str(account).isdigit() else "name"
        value = int(account) if field == "id" else str(account)
        with self.connect() as connection:
            row = connection.execute(f"SELECT * FROM accounts WHERE {field} = ?", (value,)).fetchone()
        if row is None:
            raise LookupError(f"Paper account does not exist: {account}")
        return _row(Account, row)

    def get_or_create_account(self, name: str, initial_cash, **kwargs) -> Account:
        try:
            return self.get_account(name)
        except LookupError:
            return self.create_account(name, initial_cash, **kwargs)

    def list_accounts(self) -> tuple[Account, ...]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM accounts ORDER BY name").fetchall()
        return tuple(_row(Account, row) for row in rows)

    def get_balance_micros(self, account_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cash_micros FROM account_balances WHERE account_id = ?", (account_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"Paper account does not exist: {account_id}")
        return int(row[0])

    def get_balance(self, account_id: int) -> Decimal:
        return micros_to_money(self.get_balance_micros(account_id))

    def get_positions(self, account_id: int) -> tuple[Position, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM account_positions WHERE account_id = ? ORDER BY symbol",
                (account_id,),
            ).fetchall()
        return tuple(_row(Position, row) for row in rows)

    def create_run(
        self,
        account_id: int,
        *,
        run_key: str,
        analysis_date: str,
        symbols: Iterable[str],
        config: Mapping | None = None,
        mode: str = "FORWARD_PAPER",
    ) -> tuple[AnalysisRun, bool]:
        now = _now()
        normalized = sorted({_canonical_symbol(symbol) for symbol in symbols})
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM analysis_runs WHERE account_id = ? AND run_key = ?",
                (account_id, run_key),
            ).fetchone()
            if existing is not None:
                if json.loads(existing["requested_symbols_json"]) != normalized:
                    raise ValueError(
                        f"Run {run_key!r} already exists with a different watchlist"
                    )
                return _row(AnalysisRun, existing), False
            cursor = connection.execute(
                """INSERT INTO analysis_runs
                   (account_id, run_key, analysis_date, mode, status,
                    requested_symbols_json, config_json, data_cutoff_at, started_at)
                   VALUES (?, ?, ?, ?, 'CREATED', ?, ?, ?, ?)""",
                (
                    account_id,
                    run_key,
                    analysis_date,
                    mode,
                    _json(normalized),
                    _json(config or {}),
                    f"{analysis_date}T23:59:59",
                    now,
                ),
            )
            run_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        return _row(AnalysisRun, row), True

    def set_run_status(self, run_id: int, status: str, error_text: str | None = None) -> None:
        completed = _now() if status in {"COMPLETED", "FAILED", "CANCELLED"} else None
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE analysis_runs SET status = ?, error_text = ?,
                   completed_at = COALESCE(?, completed_at) WHERE id = ?""",
                (status, error_text, completed, run_id),
            )

    def get_decisions(self, run_id: int) -> tuple[Decision, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE run_id = ? ORDER BY symbol", (run_id,)
            ).fetchall()
        return tuple(_row(Decision, row) for row in rows)

    def save_decision(
        self,
        run_id: int,
        *,
        symbol: str,
        analysis_date: str,
        rating: str,
        raw_decision_text: str,
        reference_price=None,
        price_as_of: str | None = None,
        report_path: str | None = None,
        price_snapshot_id: int | None = None,
        conviction=None,
        status: str = "COMPLETED",
        error_text: str | None = None,
    ) -> Decision:
        canonical = _canonical_symbol(symbol)
        now = _now()
        rating_value = rating.strip().upper()
        conviction_micros = money_to_micros(conviction, field="conviction") if conviction is not None else None
        reference_micros = money_to_micros(reference_price, field="reference_price") if reference_price is not None else None
        report_hash = None
        if report_path:
            report_file = Path(report_path)
            if report_file.exists() and report_file.is_file():
                report_hash = hashlib.sha256(report_file.read_bytes()).hexdigest()
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO decisions
                   (run_id, symbol, analysis_date, rating, raw_decision_text,
                    conviction_micros, reference_price_micros, price_as_of,
                    price_snapshot_id, report_path, report_hash, status, error_text,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, symbol) DO UPDATE SET
                     rating = excluded.rating,
                     raw_decision_text = excluded.raw_decision_text,
                     conviction_micros = excluded.conviction_micros,
                     reference_price_micros = excluded.reference_price_micros,
                     price_as_of = excluded.price_as_of,
                     price_snapshot_id = excluded.price_snapshot_id,
                     report_path = excluded.report_path,
                     report_hash = excluded.report_hash,
                     status = excluded.status,
                     error_text = excluded.error_text,
                     updated_at = excluded.updated_at""",
                (
                    run_id, canonical, analysis_date, rating_value, raw_decision_text,
                    conviction_micros, reference_micros, price_as_of,
                    price_snapshot_id, report_path, report_hash, status, error_text,
                    now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM decisions WHERE run_id = ? AND symbol = ?", (run_id, canonical)
            ).fetchone()
        return _row(Decision, row)

    def create_order(
        self,
        decision_id: int,
        account_id: int,
        *,
        client_order_key: str,
        symbol: str,
        side: str | None,
        quantity=None,
        notional=None,
        scheduled_for: str | None = None,
        status: str = "PENDING",
        reason: str | None = None,
        metadata: Mapping | None = None,
    ) -> Order:
        now = _now()
        quantity_nanos = quantity_to_nanos(quantity) if quantity is not None else None
        notional_value = money_to_micros(notional) if notional is not None else None
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO orders
                   (decision_id, account_id, client_order_key, symbol, side,
                    requested_quantity_nanos, requested_notional_micros,
                    scheduled_for, status, reason, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(decision_id) DO NOTHING""",
                (
                    decision_id, account_id, client_order_key, _canonical_symbol(symbol),
                    side, quantity_nanos, notional_value, scheduled_for, status,
                    reason, _json(metadata or {}), now, now,
                ),
            )
            row = connection.execute("SELECT * FROM orders WHERE decision_id = ?", (decision_id,)).fetchone()
        return _row(Order, row)

    def list_pending_orders(self, account_id: int, *, as_of_date: str) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT o.*, d.rating, d.analysis_date, r.run_key, r.id AS run_id
                   FROM orders o
                   JOIN decisions d ON d.id = o.decision_id
                   JOIN analysis_runs r ON r.id = d.run_id
                   WHERE o.account_id = ? AND o.status = 'PENDING'
                     AND date(d.analysis_date) < date(?)
                   ORDER BY CASE o.side WHEN 'SELL' THEN 0 ELSE 1 END, o.symbol""",
                (account_id, as_of_date),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def record_price(
        self,
        symbol: str,
        *,
        purpose: str,
        field: str,
        price,
        market_date: str,
        source: str = "yfinance",
    ) -> int:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO price_snapshots
                   (symbol, purpose, price_field, price_micros, market_date, source, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, purpose, price_field, market_date, source)
                   DO UPDATE SET price_micros = excluded.price_micros,
                                 captured_at = excluded.captured_at""",
                (_canonical_symbol(symbol), purpose, field, money_to_micros(price), market_date, source, _now()),
            )
            row = connection.execute(
                """SELECT id FROM price_snapshots WHERE symbol = ? AND purpose = ?
                   AND price_field = ? AND market_date = ? AND source = ?""",
                (_canonical_symbol(symbol), purpose, field, market_date, source),
            ).fetchone()
        return int(row[0])

    def execute_orders_atomically(
        self,
        account_id: int,
        executions: Iterable[Mapping],
        *,
        slippage_bps: Decimal | int | float | str = 0,
        fee=0,
        executed_at: str | None = None,
    ) -> tuple[Fill, ...]:
        items = list(executions)
        if not items:
            return ()
        bps = as_decimal(slippage_bps, field="slippage_bps")
        fee_micros = money_to_micros(fee, field="fee")
        timestamp = executed_at or _now()
        fills: list[Fill] = []
        with self.database.transaction() as connection:
            balance_row = connection.execute(
                "SELECT cash_micros FROM account_balances WHERE account_id = ?", (account_id,)
            ).fetchone()
            if balance_row is None:
                raise LookupError(f"Paper account does not exist: {account_id}")
            balance = int(balance_row[0])
            ordered = sorted(items, key=lambda item: (0 if str(item["side"]) == "SELL" else 1, int(item["order_id"])))
            for item in ordered:
                order_id = int(item["order_id"])
                order = connection.execute(
                    "SELECT * FROM orders WHERE id = ? AND account_id = ?", (order_id, account_id)
                ).fetchone()
                if order is None:
                    raise LookupError(f"Pending paper order does not exist: {order_id}")
                prior = connection.execute("SELECT * FROM fills WHERE order_id = ?", (order_id,)).fetchone()
                if prior is not None:
                    fills.append(_row(Fill, prior))
                    continue
                if order["status"] != "PENDING":
                    continue

                side = str(order["side"])
                raw_price = as_decimal(item["raw_price"], field="raw_price")
                slip = bps / Decimal("10000")
                effective = raw_price * (Decimal("1") + slip if side == "BUY" else Decimal("1") - slip)
                raw_price_micros = money_to_micros(raw_price)
                effective_price_micros = money_to_micros(effective)
                symbol = str(order["symbol"])
                position = connection.execute(
                    "SELECT * FROM account_positions WHERE account_id = ? AND symbol = ?",
                    (account_id, symbol),
                ).fetchone()
                existing_qty = int(position["quantity_nanos"]) if position else 0
                average_cost = int(position["average_cost_micros"]) if position else 0

                if side == "BUY":
                    requested = int(order["requested_notional_micros"] or 0)
                    if requested <= 0:
                        raise ValueError(f"BUY order {order_id} requires requested notional")
                    quantity_nanos = max(1, int(
                        (Decimal(requested) * Decimal(1_000_000_000) / Decimal(effective_price_micros))
                        .quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
                    ))
                    gross = notional_micros(effective_price_micros, quantity_nanos)
                    total_cost = gross + fee_micros
                    if total_cost > balance:
                        connection.execute(
                            "UPDATE orders SET status = 'REJECTED', reason = ?, updated_at = ? WHERE id = ?",
                            ("INSUFFICIENT_CASH_AT_EXECUTION", timestamp, order_id),
                        )
                        continue
                    new_qty = existing_qty + quantity_nanos
                    new_average = weighted_price_micros(existing_qty, average_cost, quantity_nanos, gross)
                    balance -= total_cost
                    connection.execute(
                        """INSERT INTO account_positions
                           (account_id, symbol, quantity_nanos, average_cost_micros,
                            last_price_micros, last_price_as_of, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(account_id, symbol) DO UPDATE SET
                             quantity_nanos = excluded.quantity_nanos,
                             average_cost_micros = excluded.average_cost_micros,
                             last_price_micros = excluded.last_price_micros,
                             last_price_as_of = excluded.last_price_as_of,
                             updated_at = excluded.updated_at""",
                        (account_id, symbol, new_qty, new_average, effective_price_micros, timestamp[:10], timestamp),
                    )
                    realized = 0
                    ledger_type = "BUY"
                    ledger_amount = -gross
                else:
                    requested_qty = int(order["requested_quantity_nanos"] or 0)
                    if position is None or requested_qty <= 0:
                        connection.execute(
                            "UPDATE orders SET status = 'REJECTED', reason = ?, updated_at = ? WHERE id = ?",
                            ("NO_OPEN_POSITION", timestamp, order_id),
                        )
                        continue
                    quantity_nanos = min(existing_qty, requested_qty)
                    gross = notional_micros(effective_price_micros, quantity_nanos)
                    realized = signed_notional_micros(
                        effective_price_micros - average_cost, quantity_nanos
                    )
                    balance += gross - fee_micros
                    remaining = existing_qty - quantity_nanos
                    if remaining <= 0:
                        connection.execute(
                            "DELETE FROM account_positions WHERE account_id = ? AND symbol = ?",
                            (account_id, symbol),
                        )
                    else:
                        connection.execute(
                            """UPDATE account_positions SET quantity_nanos = ?,
                               last_price_micros = ?, last_price_as_of = ?, updated_at = ?
                               WHERE account_id = ? AND symbol = ?""",
                            (remaining, effective_price_micros, timestamp[:10], timestamp, account_id, symbol),
                        )
                    ledger_type = "SELL"
                    ledger_amount = gross

                cursor = connection.execute(
                    """INSERT INTO fills
                       (order_id, account_id, symbol, side, quantity_nanos,
                        raw_price_micros, effective_price_micros, gross_notional_micros,
                        fee_micros, slippage_bps, realized_pnl_micros,
                        price_snapshot_id, fill_key, executed_at, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
                    (
                        order_id, account_id, symbol, side, quantity_nanos,
                        raw_price_micros, effective_price_micros, gross, fee_micros,
                        int(bps), realized, item.get("price_snapshot_id"),
                        f"order:{order_id}:fill", timestamp,
                    ),
                )
                fill_id = int(cursor.lastrowid)
                connection.execute(
                    """INSERT INTO cash_ledger
                       (account_id, entry_type, amount_micros, balance_after_micros,
                        fill_id, idempotency_key, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (account_id, ledger_type, ledger_amount, balance + fee_micros if fee_micros else balance,
                     fill_id, f"fill:{fill_id}:{ledger_type.lower()}", timestamp),
                )
                if fee_micros:
                    connection.execute(
                        """INSERT INTO cash_ledger
                           (account_id, entry_type, amount_micros, balance_after_micros,
                            fill_id, idempotency_key, occurred_at)
                           VALUES (?, 'FEE', ?, ?, ?, ?, ?)""",
                        (account_id, -fee_micros, balance, fill_id, f"fill:{fill_id}:fee", timestamp),
                    )
                connection.execute(
                    "UPDATE orders SET status = 'FILLED', updated_at = ? WHERE id = ?",
                    (timestamp, order_id),
                )
                row = connection.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone()
                fills.append(_row(Fill, row))
            if fills:
                connection.execute(
                    "UPDATE accounts SET state_revision = state_revision + 1, updated_at = ? WHERE id = ?",
                    (timestamp, account_id),
                )
        return tuple(fills)

    def record_snapshot(
        self,
        account_id: int,
        *,
        snapshot_date: str,
        prices: Mapping[str, tuple[object, str]],
        source_run_id: int | None = None,
        benchmark_price=None,
    ) -> int:
        captured = _now()
        normalized_prices = {
            _canonical_symbol(symbol): (money_to_micros(value[0]), value[1])
            for symbol, value in prices.items()
        }
        with self.database.transaction() as connection:
            account = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if account is None:
                raise LookupError(f"Paper account does not exist: {account_id}")
            cash = int(connection.execute(
                "SELECT cash_micros FROM account_balances WHERE account_id = ?", (account_id,)
            ).fetchone()[0])
            positions = connection.execute(
                "SELECT * FROM account_positions WHERE account_id = ? ORDER BY symbol", (account_id,)
            ).fetchall()
            market_value = 0
            unrealized = 0
            position_rows = []
            for position in positions:
                symbol = position["symbol"]
                price_micros, price_as_of = normalized_prices.get(
                    symbol, (int(position["last_price_micros"]), position["last_price_as_of"] or snapshot_date)
                )
                value = notional_micros(price_micros, int(position["quantity_nanos"]))
                cost = notional_micros(int(position["average_cost_micros"]), int(position["quantity_nanos"]))
                pnl = value - cost
                market_value += value
                unrealized += pnl
                connection.execute(
                    """UPDATE account_positions SET last_price_micros = ?,
                       last_price_as_of = ?, updated_at = ? WHERE account_id = ? AND symbol = ?""",
                    (price_micros, price_as_of, captured, account_id, symbol),
                )
                position_rows.append((symbol, int(position["quantity_nanos"]), int(position["average_cost_micros"]), price_micros, price_as_of, value, pnl))
            realized = int(connection.execute(
                "SELECT COALESCE(SUM(realized_pnl_micros), 0) FROM fills WHERE account_id = ?", (account_id,)
            ).fetchone()[0])
            contributions = int(connection.execute(
                """SELECT COALESCE(SUM(amount_micros), 0) FROM cash_ledger
                   WHERE account_id = ? AND entry_type IN
                   ('INITIAL_FUNDING', 'DEPOSIT', 'WITHDRAWAL', 'ADJUSTMENT')""",
                (account_id,),
            ).fetchone()[0])
            benchmark_value = None
            if benchmark_price is not None:
                current_benchmark = money_to_micros(benchmark_price)
                start_benchmark = account["benchmark_start_price_micros"]
                if start_benchmark is None:
                    start_benchmark = current_benchmark
                    connection.execute(
                        """UPDATE accounts SET benchmark_start_price_micros = ?,
                           benchmark_start_date = ?, updated_at = ? WHERE id = ?""",
                        (current_benchmark, snapshot_date, captured, account_id),
                    )
                benchmark_value = int(
                    (Decimal(contributions) * Decimal(current_benchmark) / Decimal(start_benchmark))
                    .quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
                )
            connection.execute(
                """INSERT INTO portfolio_daily_snapshots
                   (account_id, snapshot_date, source_run_id, state_revision,
                    cash_micros, market_value_micros, total_equity_micros,
                    realized_pnl_micros, unrealized_pnl_micros,
                    net_contributions_micros, benchmark_value_micros, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                     source_run_id = excluded.source_run_id,
                     state_revision = excluded.state_revision,
                     cash_micros = excluded.cash_micros,
                     market_value_micros = excluded.market_value_micros,
                     total_equity_micros = excluded.total_equity_micros,
                     realized_pnl_micros = excluded.realized_pnl_micros,
                     unrealized_pnl_micros = excluded.unrealized_pnl_micros,
                     net_contributions_micros = excluded.net_contributions_micros,
                     benchmark_value_micros = excluded.benchmark_value_micros,
                     captured_at = excluded.captured_at""",
                (
                    account_id, snapshot_date, source_run_id, int(account["state_revision"]),
                    cash, market_value, cash + market_value, realized, unrealized,
                    contributions, benchmark_value, captured,
                ),
            )
            snapshot_id = int(connection.execute(
                "SELECT id FROM portfolio_daily_snapshots WHERE account_id = ? AND snapshot_date = ?",
                (account_id, snapshot_date),
            ).fetchone()[0])
            connection.execute(
                "DELETE FROM position_daily_snapshots WHERE portfolio_snapshot_id = ?", (snapshot_id,)
            )
            connection.executemany(
                """INSERT INTO position_daily_snapshots
                   (portfolio_snapshot_id, symbol, quantity_nanos, average_cost_micros,
                    close_price_micros, price_as_of, market_value_micros,
                    unrealized_pnl_micros) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(snapshot_id, *row) for row in position_rows],
            )
        return snapshot_id

    def latest_snapshot(self, account_id: int):
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM portfolio_daily_snapshots WHERE account_id = ?
                   ORDER BY date(snapshot_date) DESC, id DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None
