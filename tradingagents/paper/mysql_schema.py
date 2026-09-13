"""Versioned MySQL DDL. Integer money and quantities use signed BIGINT."""

MIGRATIONS = ((3, "persistent paper accounts and ticker registry", (
    """CREATE TABLE IF NOT EXISTS instruments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    symbol VARCHAR(40) NOT NULL UNIQUE,
    asset_type VARCHAR(40),
    status VARCHAR(40) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAUSED')),
    paper_enabled BIGINT NOT NULL DEFAULT 1 CHECK (paper_enabled IN (0, 1)),
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    INDEX idx_instruments_paper (status, paper_enabled, symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS accounts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL UNIQUE,
    currency VARCHAR(40) NOT NULL DEFAULT 'USD',
    status VARCHAR(40) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'CLOSED')),
    strategy_version VARCHAR(40),
    strategy_config_json LONGTEXT NOT NULL,
    benchmark_symbol VARCHAR(40),
    benchmark_start_price_micros BIGINT,
    benchmark_start_date VARCHAR(40),
    state_revision BIGINT NOT NULL DEFAULT 0 CHECK (state_revision >= 0),
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS analysis_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id BIGINT NOT NULL,
    run_key VARCHAR(255) NOT NULL,
    analysis_date VARCHAR(40) NOT NULL,
    mode VARCHAR(40) NOT NULL DEFAULT 'FORWARD_PAPER',
    status VARCHAR(40) NOT NULL CHECK (status IN (
        'CREATED', 'VALUATING', 'ANALYZING', 'PARTIAL_ANALYSIS', 'PLANNED',
        'EXECUTING', 'SNAPSHOTTED', 'COMPLETED', 'FAILED', 'CANCELLED'
    )),
    requested_symbols_json LONGTEXT NOT NULL,
    config_json LONGTEXT NOT NULL,
    data_cutoff_at VARCHAR(40),
    started_at VARCHAR(40) NOT NULL,
    completed_at VARCHAR(40),
    error_text LONGTEXT,
    UNIQUE(account_id, run_key),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    INDEX idx_runs_account_date (account_id, analysis_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS price_snapshots (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    symbol VARCHAR(40) NOT NULL,
    purpose VARCHAR(40) NOT NULL CHECK (purpose IN ('DECISION', 'EXECUTION', 'VALUATION', 'BENCHMARK')),
    price_field VARCHAR(40) NOT NULL CHECK (price_field IN ('OPEN', 'CLOSE')),
    price_micros BIGINT NOT NULL CHECK (price_micros > 0),
    market_date VARCHAR(40) NOT NULL,
    source VARCHAR(40) NOT NULL DEFAULT 'yfinance',
    captured_at VARCHAR(40) NOT NULL,
    UNIQUE(symbol, purpose, price_field, market_date, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS decisions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_id BIGINT NOT NULL,
    symbol VARCHAR(40) NOT NULL,
    analysis_date VARCHAR(40) NOT NULL,
    rating VARCHAR(40) NOT NULL CHECK (rating IN ('BUY', 'OVERWEIGHT', 'HOLD', 'UNDERWEIGHT', 'SELL')),
    raw_decision_text LONGTEXT NOT NULL,
    conviction_micros BIGINT,
    reference_price_micros BIGINT,
    price_as_of VARCHAR(40),
    price_snapshot_id BIGINT,
    report_path LONGTEXT,
    report_hash VARCHAR(64),
    status VARCHAR(40) NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'FAILED')),
    error_text LONGTEXT,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    instrument_id BIGINT,
    UNIQUE(run_id, symbol),
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY (price_snapshot_id) REFERENCES price_snapshots(id) ON DELETE RESTRICT,
    FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    INDEX idx_decisions_symbol_date (symbol, analysis_date),
    INDEX idx_decisions_instrument_date (instrument_id, analysis_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    decision_id BIGINT NOT NULL UNIQUE,
    account_id BIGINT NOT NULL,
    client_order_key VARCHAR(255) NOT NULL,
    symbol VARCHAR(40) NOT NULL,
    side VARCHAR(40) CHECK (side IN ('BUY', 'SELL')),
    requested_quantity_nanos BIGINT CHECK (requested_quantity_nanos IS NULL OR requested_quantity_nanos > 0),
    requested_notional_micros BIGINT CHECK (requested_notional_micros IS NULL OR requested_notional_micros > 0),
    scheduled_for VARCHAR(40),
    status VARCHAR(40) NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'NOOP', 'REJECTED', 'CANCELLED')),
    reason LONGTEXT,
    metadata_json LONGTEXT,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    UNIQUE(account_id, client_order_key),
    FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    INDEX idx_orders_account_status (account_id, status, scheduled_for)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS fills (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL UNIQUE,
    account_id BIGINT NOT NULL,
    symbol VARCHAR(40) NOT NULL,
    side VARCHAR(40) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity_nanos BIGINT NOT NULL CHECK (quantity_nanos > 0),
    raw_price_micros BIGINT NOT NULL CHECK (raw_price_micros > 0),
    effective_price_micros BIGINT NOT NULL CHECK (effective_price_micros > 0),
    gross_notional_micros BIGINT NOT NULL CHECK (gross_notional_micros > 0),
    fee_micros BIGINT NOT NULL DEFAULT 0 CHECK (fee_micros >= 0),
    slippage_bps BIGINT NOT NULL DEFAULT 0,
    realized_pnl_micros BIGINT NOT NULL DEFAULT 0,
    price_snapshot_id BIGINT,
    fill_key VARCHAR(255) NOT NULL UNIQUE,
    executed_at VARCHAR(40) NOT NULL,
    metadata_json LONGTEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE RESTRICT,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY (price_snapshot_id) REFERENCES price_snapshots(id) ON DELETE RESTRICT,
    INDEX idx_fills_account_time (account_id, executed_at),
    INDEX idx_fills_account_symbol_time (account_id, symbol, executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS cash_ledger (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id BIGINT NOT NULL,
    entry_type VARCHAR(40) NOT NULL CHECK (entry_type IN (
        'INITIAL_FUNDING', 'DEPOSIT', 'WITHDRAWAL', 'BUY', 'SELL', 'FEE', 'ADJUSTMENT'
    )),
    amount_micros BIGINT NOT NULL,
    balance_after_micros BIGINT NOT NULL CHECK (balance_after_micros >= 0),
    fill_id BIGINT,
    idempotency_key VARCHAR(255) NOT NULL,
    note LONGTEXT,
    metadata_json LONGTEXT,
    occurred_at VARCHAR(40) NOT NULL,
    UNIQUE(account_id, idempotency_key),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY (fill_id) REFERENCES fills(id) ON DELETE RESTRICT,
    INDEX idx_cash_ledger_account_time (account_id, occurred_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS account_positions (
    account_id BIGINT NOT NULL,
    symbol VARCHAR(40) NOT NULL,
    quantity_nanos BIGINT NOT NULL CHECK (quantity_nanos > 0),
    average_cost_micros BIGINT NOT NULL CHECK (average_cost_micros > 0),
    last_price_micros BIGINT NOT NULL CHECK (last_price_micros > 0),
    last_price_as_of VARCHAR(40),
    updated_at VARCHAR(40) NOT NULL,
    PRIMARY KEY(account_id, symbol),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS portfolio_daily_snapshots (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_id BIGINT NOT NULL,
    snapshot_date VARCHAR(40) NOT NULL,
    source_run_id BIGINT,
    state_revision BIGINT NOT NULL,
    cash_micros BIGINT NOT NULL,
    market_value_micros BIGINT NOT NULL,
    total_equity_micros BIGINT NOT NULL,
    realized_pnl_micros BIGINT NOT NULL,
    unrealized_pnl_micros BIGINT NOT NULL,
    net_contributions_micros BIGINT NOT NULL,
    benchmark_value_micros BIGINT,
    captured_at VARCHAR(40) NOT NULL,
    UNIQUE(account_id, snapshot_date),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL,
    INDEX idx_snapshots_account_date (account_id, snapshot_date DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS position_daily_snapshots (
    portfolio_snapshot_id BIGINT NOT NULL,
    symbol VARCHAR(40) NOT NULL,
    quantity_nanos BIGINT NOT NULL,
    average_cost_micros BIGINT NOT NULL,
    close_price_micros BIGINT NOT NULL,
    price_as_of VARCHAR(40) NOT NULL,
    market_value_micros BIGINT NOT NULL,
    unrealized_pnl_micros BIGINT NOT NULL,
    PRIMARY KEY(portfolio_snapshot_id, symbol),
    FOREIGN KEY (portfolio_snapshot_id) REFERENCES portfolio_daily_snapshots(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE OR REPLACE VIEW account_balances AS
SELECT a.id AS account_id,
       COALESCE(SUM(l.amount_micros), 0) AS cash_micros
FROM accounts a
LEFT JOIN cash_ledger l ON l.account_id = a.id
GROUP BY a.id""",
)),)

TRIGGERS = {
    "cash_ledger_no_update": """CREATE TRIGGER cash_ledger_no_update BEFORE UPDATE ON cash_ledger
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cash_ledger is append-only'""",
    "cash_ledger_no_delete": """CREATE TRIGGER cash_ledger_no_delete BEFORE DELETE ON cash_ledger
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cash_ledger is append-only'""",
}
