"""Additive report storage; single analyses have an execution key and no paper run."""

SQLITE_REPORTS = """CREATE TABLE IF NOT EXISTS analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    run_id INTEGER REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    execution_key TEXT NOT NULL,
    report_type TEXT NOT NULL,
    content_markdown TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instrument_id, execution_key, report_type)
)"""

MYSQL_REPORTS = """CREATE TABLE IF NOT EXISTS analysis_reports (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    instrument_id BIGINT NOT NULL,
    run_id BIGINT,
    execution_key VARCHAR(64) NOT NULL,
    report_type VARCHAR(100) NOT NULL,
    content_markdown LONGTEXT NOT NULL,
    analysis_date VARCHAR(40) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    UNIQUE(instrument_id, execution_key, report_type),
    INDEX idx_reports_ticker_date (instrument_id, analysis_date),
    FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""
