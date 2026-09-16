"""CSV and JSON exports for persistent paper-trading accounts."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from tradingagents.paper.statistics import portfolio_summary


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _rows(connection, sql: str, parameters: Sequence[object] = ()) -> list[dict]:
    cursor = connection.execute(sql, parameters)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _write_csv(path: Path, rows: Iterable[dict], *, columns: Sequence[str] | None = None) -> None:
    materialized = list(rows)
    fieldnames = list(columns or (materialized[0].keys() if materialized else ()))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
            writer.writerows(materialized)


def export_account(
    connection,
    account_id: int,
    output_dir: str | Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Path:
    """Export one account's audit trail and performance data."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = portfolio_summary(
        connection, str(account_id), start_date=start_date, end_date=end_date
    )
    (output / "account_summary.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )

    date_filter = ""
    parameters: list[object] = [account_id]
    if start_date:
        date_filter += " AND date({column}) >= date(?)"
        parameters.append(start_date)
    if end_date:
        date_filter += " AND date({column}) <= date(?)"
        parameters.append(end_date)

    def filtered(column: str) -> tuple[str, list[object]]:
        return date_filter.format(column=column), list(parameters)

    fill_filter, fill_params = filtered("f.executed_at")
    _write_csv(
        output / "trades.csv",
        _rows(
            connection,
            """SELECT f.id, r.run_key, d.analysis_date AS decision_at,
                      f.executed_at, f.symbol, d.rating, f.side,
                      f.quantity_nanos, f.raw_price_micros,
                      f.effective_price_micros, f.gross_notional_micros,
                      f.fee_micros, f.slippage_bps, f.realized_pnl_micros,
                      o.status
               FROM fills f
               JOIN orders o ON o.id = f.order_id
               JOIN decisions d ON d.id = o.decision_id
               JOIN analysis_runs r ON r.id = d.run_id
               WHERE f.account_id = ?"""
            + fill_filter
            + " ORDER BY f.executed_at, f.id",
            fill_params,
        ),
    )

    ledger_filter, ledger_params = filtered("occurred_at")
    _write_csv(
        output / "cash_ledger.csv",
        _rows(
            connection,
            "SELECT * FROM cash_ledger WHERE account_id = ?"
            + ledger_filter
            + " ORDER BY occurred_at, id",
            ledger_params,
        ),
    )

    snapshot_filter, snapshot_params = filtered("snapshot_date")
    daily = _rows(
        connection,
        "SELECT * FROM portfolio_daily_snapshots WHERE account_id = ?"
        + snapshot_filter
        + " ORDER BY snapshot_date, id",
        snapshot_params,
    )
    _write_csv(output / "daily_portfolio.csv", daily)
    snapshot_ids = [row["id"] for row in daily]
    daily_positions: list[dict] = []
    if snapshot_ids:
        placeholders = ",".join("?" for _ in snapshot_ids)
        daily_positions = _rows(
            connection,
            f"""SELECT p.snapshot_date, s.*
                FROM position_daily_snapshots s
                JOIN portfolio_daily_snapshots p ON p.id = s.portfolio_snapshot_id
                WHERE s.portfolio_snapshot_id IN ({placeholders})
                ORDER BY p.snapshot_date, s.symbol""",
            snapshot_ids,
        )
    _write_csv(output / "daily_positions.csv", daily_positions)

    decisions_filter, decisions_params = filtered("d.analysis_date")
    _write_csv(
        output / "decisions.csv",
        _rows(
            connection,
            """SELECT d.*, r.run_key FROM decisions d
               JOIN analysis_runs r ON r.id = d.run_id
               WHERE r.account_id = ?"""
            + decisions_filter
            + " ORDER BY d.analysis_date, d.symbol",
            decisions_params,
        ),
    )
    _write_csv(
        output / "orders.csv",
        _rows(
            connection,
            """SELECT o.*, d.analysis_date, d.rating, r.run_key
               FROM orders o
               JOIN decisions d ON d.id = o.decision_id
               JOIN analysis_runs r ON r.id = d.run_id
               WHERE o.account_id = ?"""
            + decisions_filter
            + " ORDER BY d.analysis_date, o.symbol",
            decisions_params,
        ),
    )
    _write_csv(
        output / "ticker_summary.csv",
        [
            {key: (str(value) if isinstance(value, Decimal) else value)
             for key, value in asdict(ticker).items()}
            for ticker in summary.tickers
        ],
    )
    return output


__all__ = ["export_account"]
