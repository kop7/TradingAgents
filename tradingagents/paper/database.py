"""SQLite schema and connection management for persistent paper trading."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'CLOSED')),
    strategy_version TEXT,
    strategy_config_json TEXT NOT NULL DEFAULT '{}',
    benchmark_symbol TEXT,
    benchmark_start_price_micros INTEGER,
    benchmark_start_date TEXT,
    state_revision INTEGER NOT NULL DEFAULT 0 CHECK (state_revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    entry_type TEXT NOT NULL CHECK (entry_type IN (
        'INITIAL_FUNDING', 'DEPOSIT', 'WITHDRAWAL', 'BUY', 'SELL', 'FEE', 'ADJUSTMENT'
    )),
    amount_micros INTEGER NOT NULL,
    balance_after_micros INTEGER NOT NULL CHECK (balance_after_micros >= 0),
    fill_id INTEGER REFERENCES fills(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    note TEXT,
    metadata_json TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE(account_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    run_key TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'FORWARD_PAPER',
    status TEXT NOT NULL CHECK (status IN (
        'CREATED', 'VALUATING', 'ANALYZING', 'PARTIAL_ANALYSIS', 'PLANNED',
        'EXECUTING', 'SNAPSHOTTED', 'COMPLETED', 'FAILED', 'CANCELLED'
    )),
    requested_symbols_json TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    data_cutoff_at TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_text TEXT,
    UNIQUE(account_id, run_key)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('DECISION', 'EXECUTION', 'VALUATION', 'BENCHMARK')),
    price_field TEXT NOT NULL CHECK (price_field IN ('OPEN', 'CLOSE')),
    price_micros INTEGER NOT NULL CHECK (price_micros > 0),
    market_date TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'yfinance',
    captured_at TEXT NOT NULL,
    UNIQUE(symbol, purpose, price_field, market_date, source)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    symbol TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('BUY', 'OVERWEIGHT', 'HOLD', 'UNDERWEIGHT', 'SELL')),
    raw_decision_text TEXT NOT NULL,
    conviction_micros INTEGER,
    reference_price_micros INTEGER,
    price_as_of TEXT,
    price_snapshot_id INTEGER REFERENCES price_snapshots(id) ON DELETE RESTRICT,
    report_path TEXT,
    report_hash TEXT,
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'FAILED')),
    error_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL UNIQUE REFERENCES decisions(id) ON DELETE RESTRICT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    client_order_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT CHECK (side IN ('BUY', 'SELL')),
    requested_quantity_nanos INTEGER CHECK (requested_quantity_nanos IS NULL OR requested_quantity_nanos > 0),
    requested_notional_micros INTEGER CHECK (requested_notional_micros IS NULL OR requested_notional_micros > 0),
    scheduled_for TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'NOOP', 'REJECTED', 'CANCELLED')),
    reason TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, client_order_key)
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE RESTRICT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity_nanos INTEGER NOT NULL CHECK (quantity_nanos > 0),
    raw_price_micros INTEGER NOT NULL CHECK (raw_price_micros > 0),
    effective_price_micros INTEGER NOT NULL CHECK (effective_price_micros > 0),
    gross_notional_micros INTEGER NOT NULL CHECK (gross_notional_micros > 0),
    fee_micros INTEGER NOT NULL DEFAULT 0 CHECK (fee_micros >= 0),
    slippage_bps INTEGER NOT NULL DEFAULT 0,
    realized_pnl_micros INTEGER NOT NULL DEFAULT 0,
    price_snapshot_id INTEGER REFERENCES price_snapshots(id) ON DELETE RESTRICT,
    fill_key TEXT NOT NULL UNIQUE,
    executed_at TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS account_positions (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    symbol TEXT NOT NULL,
    quantity_nanos INTEGER NOT NULL CHECK (quantity_nanos > 0),
    average_cost_micros INTEGER NOT NULL CHECK (average_cost_micros > 0),
    last_price_micros INTEGER NOT NULL CHECK (last_price_micros > 0),
    last_price_as_of TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(account_id, symbol)
);

CREATE TABLE IF NOT EXISTS portfolio_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    snapshot_date TEXT NOT NULL,
    source_run_id INTEGER REFERENCES analysis_runs(id) ON DELETE SET NULL,
    state_revision INTEGER NOT NULL,
    cash_micros INTEGER NOT NULL,
    market_value_micros INTEGER NOT NULL,
    total_equity_micros INTEGER NOT NULL,
    realized_pnl_micros INTEGER NOT NULL,
    unrealized_pnl_micros INTEGER NOT NULL,
    net_contributions_micros INTEGER NOT NULL,
    benchmark_value_micros INTEGER,
    captured_at TEXT NOT NULL,
    UNIQUE(account_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS position_daily_snapshots (
    portfolio_snapshot_id INTEGER NOT NULL
        REFERENCES portfolio_daily_snapshots(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    quantity_nanos INTEGER NOT NULL,
    average_cost_micros INTEGER NOT NULL,
    close_price_micros INTEGER NOT NULL,
    price_as_of TEXT NOT NULL,
    market_value_micros INTEGER NOT NULL,
    unrealized_pnl_micros INTEGER NOT NULL,
    PRIMARY KEY(portfolio_snapshot_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_cash_ledger_account_time
    ON cash_ledger(account_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_runs_account_date
    ON analysis_runs(account_id, analysis_date, status);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol_date
    ON decisions(symbol, analysis_date);
CREATE INDEX IF NOT EXISTS idx_orders_account_status
    ON orders(account_id, status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_fills_account_time
    ON fills(account_id, executed_at);
CREATE INDEX IF NOT EXISTS idx_fills_account_symbol_time
    ON fills(account_id, symbol, executed_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_account_date
    ON portfolio_daily_snapshots(account_id, snapshot_date DESC);

CREATE TRIGGER IF NOT EXISTS cash_ledger_no_update
BEFORE UPDATE ON cash_ledger BEGIN
    SELECT RAISE(ABORT, 'cash_ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS cash_ledger_no_delete
BEFORE DELETE ON cash_ledger BEGIN
    SELECT RAISE(ABORT, 'cash_ledger is append-only');
END;

CREATE VIEW IF NOT EXISTS account_balances AS
SELECT a.id AS account_id,
       COALESCE(SUM(l.amount_micros), 0) AS cash_micros
FROM accounts a
LEFT JOIN cash_ledger l ON l.account_id = a.id
GROUP BY a.id;
"""


class PaperDatabase:
    """Own a versioned SQLite database dedicated to v2 paper trading."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self) -> PaperDatabase:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Paper database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            connection.executescript(SCHEMA_SQL)
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, "clean persistent paper-trading schema", now),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Paper database integrity check failed: {integrity}")
        return self

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

