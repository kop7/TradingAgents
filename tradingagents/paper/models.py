"""Typed records exposed by the persistent paper-trading repository."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TextEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AccountStatus(TextEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class LedgerEntryType(TextEnum):
    INITIAL_FUNDING = "INITIAL_FUNDING"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"


class RunStatus(TextEnum):
    CREATED = "CREATED"
    VALUATING = "VALUATING"
    ANALYZING = "ANALYZING"
    PARTIAL_ANALYSIS = "PARTIAL_ANALYSIS"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    SNAPSHOTTED = "SNAPSHOTTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DecisionRating(TextEnum):
    BUY = "BUY"
    OVERWEIGHT = "OVERWEIGHT"
    HOLD = "HOLD"
    UNDERWEIGHT = "UNDERWEIGHT"
    SELL = "SELL"


class DecisionStatus(TextEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrderSide(TextEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(TextEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    NOOP = "NOOP"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    currency: str
    status: str
    strategy_version: str | None
    strategy_config_json: str
    benchmark_symbol: str | None
    benchmark_start_price_micros: int | None
    benchmark_start_date: str | None
    state_revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CashLedgerEntry:
    id: int
    account_id: int
    entry_type: str
    amount_micros: int
    balance_after_micros: int
    fill_id: int | None
    idempotency_key: str
    note: str | None
    metadata_json: str | None
    occurred_at: str


@dataclass(frozen=True)
class AnalysisRun:
    id: int
    account_id: int
    run_key: str
    analysis_date: str
    mode: str
    status: str
    requested_symbols_json: str
    config_json: str
    data_cutoff_at: str | None
    started_at: str
    completed_at: str | None
    error_text: str | None


@dataclass(frozen=True)
class Decision:
    id: int
    run_id: int
    symbol: str
    analysis_date: str
    rating: str
    raw_decision_text: str
    conviction_micros: int | None
    reference_price_micros: int | None
    price_as_of: str | None
    price_snapshot_id: int | None
    report_path: str | None
    report_hash: str | None
    status: str
    error_text: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Order:
    id: int
    decision_id: int
    account_id: int
    client_order_key: str
    symbol: str
    side: str
    requested_quantity_nanos: int | None
    requested_notional_micros: int | None
    scheduled_for: str | None
    status: str
    reason: str | None
    created_at: str
    updated_at: str
    metadata_json: str | None


@dataclass(frozen=True)
class Fill:
    id: int
    order_id: int
    account_id: int
    symbol: str
    side: str
    quantity_nanos: int
    raw_price_micros: int
    effective_price_micros: int
    gross_notional_micros: int
    fee_micros: int
    slippage_bps: int
    realized_pnl_micros: int
    price_snapshot_id: int | None
    fill_key: str
    executed_at: str
    metadata_json: str | None


@dataclass(frozen=True)
class Position:
    account_id: int
    symbol: str
    quantity_nanos: int
    average_cost_micros: int
    last_price_micros: int
    last_price_as_of: str | None
    updated_at: str


@dataclass(frozen=True)
class FillExecution:
    fill: Fill
    position: Position | None
    balance_micros: int
    duplicate: bool = False
