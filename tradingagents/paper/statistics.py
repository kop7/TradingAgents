"""Deterministic statistics for the v2 paper-trading ledger.

The functions in this module are deliberately read-only.  They accept either a
``sqlite3.Connection`` or any repository/query object exposing SQLite's small
``execute(sql, parameters)`` surface, which keeps them straightforward to unit
test and prevents reporting from mutating account state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

MICROS = Decimal("1000000")
NANOS = Decimal("1000000000")
ZERO = Decimal(0)
ONE = Decimal(1)


@runtime_checkable
class QuerySource(Protocol):
    """Minimal read interface implemented by sqlite connections/repositories."""

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> Any: ...


@dataclass(frozen=True)
class EquityPoint:
    snapshot_date: str
    cash: Decimal
    market_value: Decimal
    total_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    net_contributions: Decimal
    benchmark_value: Decimal | None
    daily_return: Decimal
    cumulative_return: Decimal
    benchmark_return: Decimal | None
    drawdown: Decimal


@dataclass(frozen=True)
class TickerSummary:
    symbol: str
    bought: Decimal
    sold: Decimal
    buy_count: int
    sell_count: int
    current_quantity: Decimal
    average_cost: Decimal
    current_price: Decimal
    current_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal


@dataclass(frozen=True)
class PortfolioSummary:
    account_id: str
    account_name: str
    currency: str
    benchmark_symbol: str | None
    start_date: str | None
    end_date: str | None
    trading_days: int
    start_equity: Decimal
    end_cash: Decimal
    end_market_value: Decimal
    end_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    net_contributions: Decimal
    portfolio_return: Decimal
    benchmark_return: Decimal | None
    alpha: Decimal | None
    relative_return: Decimal | None
    max_drawdown: Decimal
    best_day_date: str | None
    best_day_return: Decimal | None
    worst_day_date: str | None
    worst_day_return: Decimal | None
    equity_curve: tuple[EquityPoint, ...]
    tickers: tuple[TickerSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-friendly mapping while retaining Decimals."""

        return asdict(self)


def _money(value: int | None) -> Decimal:
    return Decimal(value or 0) / MICROS


def _quantity(value: int | None) -> Decimal:
    return Decimal(value or 0) / NANOS


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator if denominator else ZERO


def _fetchall(
    source: QuerySource, sql: str, parameters: Sequence[object] = ()
) -> list[dict[str, Any]]:
    cursor = source.execute(sql, parameters)
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _fetchone(
    source: QuerySource, sql: str, parameters: Sequence[object] = ()
) -> dict[str, Any] | None:
    rows = _fetchall(source, sql, parameters)
    return rows[0] if rows else None


def _date_clause(
    column: str, start_date: str | None, end_date: str | None
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if start_date is not None:
        clauses.append(f"date({column}) >= date(?)")
        parameters.append(start_date)
    if end_date is not None:
        clauses.append(f"date({column}) <= date(?)")
        parameters.append(end_date)
    return (" AND " + " AND ".join(clauses) if clauses else "", parameters)


def equity_curve(
    source: QuerySource,
    account_id: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[EquityPoint, ...]:
    """Build the account's cash-flow-adjusted equity and drawdown curve.

    ``net_contributions_micros`` is treated as a cumulative value.  Therefore a
    deposit or withdrawal does not become investment performance.  The first
    snapshot in a range is the return baseline; when ``start_date`` is supplied,
    the latest earlier snapshot is fetched solely as the opening baseline.
    """

    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    end_sql, end_parameters = _date_clause("snapshot_date", None, end_date)
    rows = _fetchall(
        source,
        """SELECT snapshot_date, cash_micros, market_value_micros,
                  total_equity_micros, realized_pnl_micros,
                  unrealized_pnl_micros, net_contributions_micros,
                  benchmark_value_micros
           FROM portfolio_daily_snapshots
           WHERE account_id = ?"""
        + end_sql
        + " ORDER BY date(snapshot_date), id",
        [account_id, *end_parameters],
    )
    if not rows:
        return ()

    first_visible = 0
    if start_date is not None:
        visible_indexes = [
            index for index, row in enumerate(rows) if row["snapshot_date"] >= start_date
        ]
        if not visible_indexes:
            return ()
        first_visible = visible_indexes[0]
        calculation_start = max(0, first_visible - 1)
    else:
        calculation_start = 0

    calculation_rows = rows[calculation_start:]
    base_benchmark = (
        _money(calculation_rows[0]["benchmark_value_micros"])
        if calculation_rows[0]["benchmark_value_micros"] is not None
        else None
    )
    previous_equity: Decimal | None = None
    previous_contributions: Decimal | None = None
    wealth_index = ONE
    peak = ONE
    points: list[EquityPoint] = []

    for row in calculation_rows:
        equity = _money(row["total_equity_micros"])
        contributions = _money(row["net_contributions_micros"])
        benchmark_value = (
            _money(row["benchmark_value_micros"])
            if row["benchmark_value_micros"] is not None
            else None
        )

        if previous_equity is None:
            daily_return = ZERO
        else:
            flow = contributions - (previous_contributions or ZERO)
            daily_return = _ratio(equity - flow, previous_equity) - ONE
            wealth_index *= ONE + daily_return

        peak = max(peak, wealth_index)
        drawdown = _ratio(wealth_index, peak) - ONE
        cumulative_return = wealth_index - ONE
        benchmark_return = (
            _ratio(benchmark_value, base_benchmark) - ONE
            if benchmark_value is not None and base_benchmark
            else None
        )

        points.append(
            EquityPoint(
                snapshot_date=row["snapshot_date"],
                cash=_money(row["cash_micros"]),
                market_value=_money(row["market_value_micros"]),
                total_equity=equity,
                realized_pnl=_money(row["realized_pnl_micros"]),
                unrealized_pnl=_money(row["unrealized_pnl_micros"]),
                net_contributions=contributions,
                benchmark_value=benchmark_value,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                benchmark_return=benchmark_return,
                drawdown=drawdown,
            )
        )
        previous_equity = equity
        previous_contributions = contributions

    # The predecessor is a calculation baseline, not part of the requested CSV
    # or report range. Its effect remains in the first visible day's return.
    if start_date is not None and calculation_start < first_visible:
        points = points[1:]
    return tuple(points)


def ticker_summaries(
    source: QuerySource,
    account_id: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[TickerSummary, ...]:
    """Aggregate fills in the range and positions at the final snapshot."""

    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    fill_sql, fill_parameters = _date_clause("executed_at", start_date, end_date)
    fills = _fetchall(
        source,
        """SELECT symbol,
                  COALESCE(SUM(CASE WHEN side = 'BUY'
                                    THEN gross_notional_micros ELSE 0 END), 0)
                      AS bought_micros,
                  COALESCE(SUM(CASE WHEN side = 'SELL'
                                    THEN gross_notional_micros ELSE 0 END), 0)
                      AS sold_micros,
                  SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
                  SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
                  COALESCE(SUM(realized_pnl_micros), 0) AS realized_pnl_micros
           FROM fills
           WHERE account_id = ?"""
        + fill_sql
        + " GROUP BY symbol",
        [account_id, *fill_parameters],
    )

    snapshot_filter = ""
    snapshot_parameters: list[object] = [account_id]
    if end_date is not None:
        snapshot_filter = " AND date(snapshot_date) <= date(?)"
        snapshot_parameters.append(end_date)
    final_snapshot = _fetchone(
        source,
        """SELECT id FROM portfolio_daily_snapshots
           WHERE account_id = ?"""
        + snapshot_filter
        + " ORDER BY date(snapshot_date) DESC, id DESC LIMIT 1",
        snapshot_parameters,
    )
    positions: list[dict[str, Any]] = []
    if final_snapshot is not None:
        positions = _fetchall(
            source,
            """SELECT symbol, quantity_nanos, average_cost_micros,
                      close_price_micros, market_value_micros,
                      unrealized_pnl_micros
               FROM position_daily_snapshots
               WHERE portfolio_snapshot_id = ?""",
            [final_snapshot["id"]],
        )

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in fills:
        by_symbol[row["symbol"]] = dict(row)
    for row in positions:
        by_symbol.setdefault(row["symbol"], {}).update(row)

    result: list[TickerSummary] = []
    for symbol in sorted(by_symbol):
        row = by_symbol[symbol]
        realized = _money(row.get("realized_pnl_micros"))
        unrealized = _money(row.get("unrealized_pnl_micros"))
        result.append(
            TickerSummary(
                symbol=symbol,
                bought=_money(row.get("bought_micros")),
                sold=_money(row.get("sold_micros")),
                buy_count=int(row.get("buy_count") or 0),
                sell_count=int(row.get("sell_count") or 0),
                current_quantity=_quantity(row.get("quantity_nanos")),
                average_cost=_money(row.get("average_cost_micros")),
                current_price=_money(row.get("close_price_micros")),
                current_value=_money(row.get("market_value_micros")),
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_pnl=realized + unrealized,
            )
        )
    return tuple(result)


def portfolio_summary(
    source: QuerySource,
    account_id: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> PortfolioSummary:
    """Return portfolio, benchmark, drawdown and per-ticker statistics."""

    account = _fetchone(
        source,
        """SELECT id, name, currency, benchmark_symbol
           FROM accounts WHERE id = ?""",
        [account_id],
    )
    if account is None:
        raise LookupError(f"Paper account does not exist: {account_id}")

    curve = equity_curve(
        source, account_id, start_date=start_date, end_date=end_date
    )
    tickers = ticker_summaries(
        source, account_id, start_date=start_date, end_date=end_date
    )
    if not curve:
        return PortfolioSummary(
            account_id=account_id,
            account_name=account["name"],
            currency=account["currency"],
            benchmark_symbol=account["benchmark_symbol"],
            start_date=None,
            end_date=None,
            trading_days=0,
            start_equity=ZERO,
            end_cash=ZERO,
            end_market_value=ZERO,
            end_equity=ZERO,
            realized_pnl=ZERO,
            unrealized_pnl=ZERO,
            total_pnl=ZERO,
            net_contributions=ZERO,
            portfolio_return=ZERO,
            benchmark_return=None,
            alpha=None,
            relative_return=None,
            max_drawdown=ZERO,
            best_day_date=None,
            best_day_return=None,
            worst_day_date=None,
            worst_day_return=None,
            equity_curve=(),
            tickers=tickers,
        )

    first, last = curve[0], curve[-1]
    portfolio_return = last.cumulative_return
    benchmark_return = last.benchmark_return
    alpha = (
        portfolio_return - benchmark_return
        if benchmark_return is not None
        else None
    )
    relative_return = (
        (ONE + portfolio_return) / (ONE + benchmark_return) - ONE
        if benchmark_return is not None and benchmark_return != -ONE
        else None
    )
    performance_days = curve[1:] if start_date is None else curve
    best = max(performance_days, key=lambda point: point.daily_return, default=None)
    worst = min(performance_days, key=lambda point: point.daily_return, default=None)

    return PortfolioSummary(
        account_id=account_id,
        account_name=account["name"],
        currency=account["currency"],
        benchmark_symbol=account["benchmark_symbol"],
        start_date=first.snapshot_date,
        end_date=last.snapshot_date,
        trading_days=len(curve),
        start_equity=first.total_equity,
        end_cash=last.cash,
        end_market_value=last.market_value,
        end_equity=last.total_equity,
        realized_pnl=last.realized_pnl,
        unrealized_pnl=last.unrealized_pnl,
        total_pnl=last.realized_pnl + last.unrealized_pnl,
        net_contributions=last.net_contributions - first.net_contributions,
        portfolio_return=portfolio_return,
        benchmark_return=benchmark_return,
        alpha=alpha,
        relative_return=relative_return,
        max_drawdown=min(point.drawdown for point in curve),
        best_day_date=best.snapshot_date if best else None,
        best_day_return=best.daily_return if best else None,
        worst_day_date=worst.snapshot_date if worst else None,
        worst_day_return=worst.daily_return if worst else None,
        equity_curve=curve,
        tickers=tickers,
    )


__all__ = [
    "EquityPoint",
    "PortfolioSummary",
    "QuerySource",
    "TickerSummary",
    "equity_curve",
    "portfolio_summary",
    "ticker_summaries",
]
