"""Parameterized cockpit queries. No migrations, vendors or trading services."""

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass

from tradingagents.paper.mysql import MySQLDatabase
from tradingagents.paper.statistics import equity_curve, ticker_summaries


@contextmanager
def read_connection():
    if os.getenv("DB_CONNECTION", "mysql").lower() != "mysql":
        raise ValueError("Cockpit zahtijeva DB_CONNECTION=mysql.")
    with MySQLDatabase.from_env().connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        yield connection


@dataclass(frozen=True)
class Filters:
    account_id: int | None
    start: str
    end: str
    ticker: str = ""
    status: str = ""

    def __post_init__(self):
        if self.start > self.end:
            raise ValueError("Početni datum mora biti prije završnog.")


class CockpitData:
    def __init__(self, connection):
        self.connection = connection

    def rows(self, sql, params=()):
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    def accounts(self):
        return self.rows("SELECT id, name, currency, status FROM accounts ORDER BY name")

    def account_details(self, account_id):
        rows = self.rows(
            "SELECT a.id, a.name, a.currency, a.status, a.strategy_config_json, a.state_revision, "
            "b.cash_micros FROM accounts a JOIN account_balances b ON b.account_id=a.id "
            "WHERE a.id=?", [account_id],
        )
        if not rows:
            raise LookupError("Račun ne postoji.")
        return rows[0]

    def deposits(self, account_id):
        return self.rows(
            "SELECT occurred_at, amount_micros, balance_after_micros FROM cash_ledger "
            "WHERE account_id=? AND entry_type='DEPOSIT' ORDER BY id DESC LIMIT 20", [account_id],
        )

    def curve(self, filters):
        return equity_curve(self.connection, filters.account_id,
                            start_date=filters.start, end_date=filters.end)

    def ticker_pnl(self, filters):
        return ticker_summaries(self.connection, filters.account_id,
                                start_date=filters.start, end_date=filters.end)

    def runs(self, filters, page=0, size=25):
        where = "r.account_id = ? AND r.analysis_date BETWEEN ? AND ?"
        params = [filters.account_id, filters.start, filters.end]
        if filters.status:
            where += " AND r.status = ?"
            params.append(filters.status)
        if filters.ticker:
            # Include requested tickers even when analysis failed before a decision existed.
            where += (" AND (EXISTS (SELECT 1 FROM decisions d WHERE d.run_id=r.id "
                      "AND d.symbol=?) OR r.requested_symbols_json LIKE ? ESCAPE '!')")
            value = json.dumps(filters.ticker, ensure_ascii=False)
            value = value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            params.extend([filters.ticker, "%" + value + "%"])
        return self.rows(
            "SELECT r.id, r.analysis_date, r.status, r.requested_symbols_json, "
            "r.started_at, r.completed_at, r.error_text, "
            "(SELECT COUNT(*) FROM decisions d WHERE d.run_id=r.id "
            "AND d.status='COMPLETED') AS completed_tickers, "
            "(SELECT COUNT(*) FROM decisions d WHERE d.run_id=r.id "
            "AND d.status='FAILED') AS failed_tickers FROM analysis_runs r WHERE "
            + where + " ORDER BY r.analysis_date DESC, r.id DESC LIMIT ? OFFSET ?",
            [*params, size + 1, page * size],
        )

    def decisions(self, account_id, run_id):
        return self.rows(
            "SELECT d.symbol, d.rating, d.status, d.error_text, d.price_as_of "
            "FROM decisions d JOIN analysis_runs r ON r.id=d.run_id "
            "WHERE r.account_id=? AND r.id=? ORDER BY d.symbol", [account_id, run_id],
        )

    def reports(self, filters, page=0, size=25, report_id=None):
        where = "ar.analysis_date BETWEEN ? AND ?"
        params = [filters.start, filters.end]
        if filters.account_id is None:
            where += " AND ar.run_id IS NULL"
        else:
            where += " AND r.account_id=?"
            params.append(filters.account_id)
        if filters.ticker:
            where += " AND i.symbol=?"
            params.append(filters.ticker)
        if filters.status and filters.account_id is not None:
            where += " AND r.status=?"
            params.append(filters.status)
        fields = ("ar.id, i.symbol, ar.analysis_date, ar.execution_key, ar.run_id, "
                  "ar.report_type")
        if report_id is not None:
            fields += ", ar.content_markdown"
            where += " AND ar.id=?"
            params.append(report_id)
        return self.rows(
            "SELECT " + fields + " FROM analysis_reports ar "
            "JOIN instruments i ON i.id=ar.instrument_id "
            "LEFT JOIN analysis_runs r ON r.id=ar.run_id WHERE " + where
            + " ORDER BY ar.analysis_date DESC, ar.id DESC LIMIT ? OFFSET ?",
            [*params, 1 if report_id is not None else size + 1,
             0 if report_id is not None else page * size],
        )

    def valuation_dates(self, filters):
        return self.rows(
            "SELECT p.symbol, p.price_as_of FROM position_daily_snapshots p "
            "JOIN portfolio_daily_snapshots s ON s.id=p.portfolio_snapshot_id "
            "WHERE s.account_id=? AND s.snapshot_date=(SELECT MAX(snapshot_date) "
            "FROM portfolio_daily_snapshots WHERE account_id=? AND snapshot_date BETWEEN ? AND ?) "
            "ORDER BY p.symbol",
            [filters.account_id, filters.account_id, filters.start, filters.end],
        )
