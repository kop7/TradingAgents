"""Pure OHLCV price selection for paper execution and valuation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd


class PriceUnavailableError(ValueError):
    """Raised when an OHLCV frame has no usable bar for the requested rule."""


@dataclass(frozen=True)
class PricePoint:
    market_date: date
    field: str
    price: Decimal


def _timestamp(value: str | date | pd.Timestamp, *, name: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{name} must be a valid date")
    if getattr(parsed, "tzinfo", None) is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _normalized_rows(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty:
        raise PriceUnavailableError("OHLCV data is empty")
    frame = data.copy()
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce", utc=True).dt.tz_localize(None)
    elif isinstance(frame.index, pd.DatetimeIndex):
        dates = pd.Series(
            pd.to_datetime(frame.index, errors="coerce", utc=True).tz_localize(None),
            index=frame.index,
        )
    else:
        raise PriceUnavailableError("OHLCV data requires a Date column or DatetimeIndex")
    frame = frame.assign(_market_date=dates.to_numpy())
    frame = frame.dropna(subset=["_market_date"])
    frame["_market_date"] = frame["_market_date"].dt.normalize()
    return frame.sort_values("_market_date", kind="stable")


def _point(row: pd.Series, field: str) -> PricePoint:
    if field not in row.index:
        raise PriceUnavailableError(f"OHLCV data has no {field} column")
    numeric = pd.to_numeric(pd.Series([row[field]]), errors="coerce").iloc[0]
    if pd.isna(numeric) or float(numeric) <= 0:
        raise PriceUnavailableError(f"Selected {field} price is missing or non-positive")
    return PricePoint(
        market_date=row["_market_date"].date(),
        field=field,
        price=Decimal(str(numeric)),
    )


def first_open_after_decision(
    data: pd.DataFrame,
    *,
    decision_date: str | date | pd.Timestamp,
    as_of_date: str | date | pd.Timestamp,
) -> PricePoint:
    """Select the first positive Open after decision_date and through as_of_date."""
    decision = _timestamp(decision_date, name="decision_date")
    as_of = _timestamp(as_of_date, name="as_of_date")
    if as_of <= decision:
        raise ValueError("as_of_date must be after decision_date")
    rows = _normalized_rows(data)
    candidates = rows[(rows["_market_date"] > decision) & (rows["_market_date"] <= as_of)]
    if candidates.empty:
        raise PriceUnavailableError("No market open exists after decision_date through as_of_date")
    return _point(candidates.iloc[0], "Open")


def valuation_close(
    data: pd.DataFrame,
    *,
    valuation_date: str | date | pd.Timestamp,
) -> PricePoint:
    """Select the latest positive Close on or before valuation_date."""
    valuation = _timestamp(valuation_date, name="valuation_date")
    rows = _normalized_rows(data)
    candidates = rows[rows["_market_date"] <= valuation]
    if candidates.empty:
        raise PriceUnavailableError("No market close exists on or before valuation_date")
    return _point(candidates.iloc[-1], "Close")


OHLCVLoader = Callable[[str, str], pd.DataFrame]


def fetch_first_open_after_decision(
    symbol: str,
    *,
    decision_date: str,
    as_of_date: str,
    loader: OHLCVLoader | None = None,
) -> PricePoint:
    """Load OHLCV through as_of_date and apply the next-open execution rule."""
    if loader is None:
        from tradingagents.dataflows.stockstats_utils import load_ohlcv

        loader = load_ohlcv
    return first_open_after_decision(
        loader(symbol, as_of_date),
        decision_date=decision_date,
        as_of_date=as_of_date,
    )


def fetch_valuation_close(
    symbol: str,
    *,
    valuation_date: str,
    loader: OHLCVLoader | None = None,
) -> PricePoint:
    """Load OHLCV through valuation_date and select its latest available close."""
    if loader is None:
        from tradingagents.dataflows.stockstats_utils import load_ohlcv

        loader = load_ohlcv
    return valuation_close(loader(symbol, valuation_date), valuation_date=valuation_date)
