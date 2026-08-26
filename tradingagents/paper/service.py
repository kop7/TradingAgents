"""High-level orchestration for persistent forward paper trading."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from tradingagents.paper.allocator import (
    AllocationDecision,
    AllocationPlan,
    AllocationPolicy,
    PositionState,
    build_allocation_plan,
)
from tradingagents.paper.money import micros_to_money, nanos_to_quantity
from tradingagents.paper.prices import (
    PriceUnavailableError,
    fetch_first_open_after_decision,
    fetch_valuation_close,
)
from tradingagents.paper.repository import PaperRepository


@dataclass(frozen=True)
class PendingExecutionResult:
    fills: tuple
    errors: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_id: int
    errors: tuple[str, ...]


class PersistentPaperService:
    def __init__(
        self,
        repository: PaperRepository,
        *,
        policy: AllocationPolicy | None = None,
        slippage_bps=5,
        price_loader: Callable | None = None,
    ):
        self.repository = repository
        self.policy = policy or AllocationPolicy()
        self.slippage_bps = Decimal(str(slippage_bps))
        self.price_loader = price_loader

    def execute_pending(self, account_id: int, *, as_of_date: str) -> PendingExecutionResult:
        pending = self.repository.list_pending_orders(account_id, as_of_date=as_of_date)
        if not pending:
            return PendingExecutionResult((), ())
        executions = []
        errors = []
        for order in pending:
            try:
                point = fetch_first_open_after_decision(
                    order["symbol"],
                    decision_date=order["analysis_date"],
                    as_of_date=as_of_date,
                    loader=self.price_loader,
                )
                price_snapshot_id = self.repository.record_price(
                    order["symbol"],
                    purpose="EXECUTION",
                    field="OPEN",
                    price=point.price,
                    market_date=point.market_date.isoformat(),
                )
                executions.append(
                    {
                        "order_id": order["id"],
                        "side": order["side"],
                        "raw_price": point.price,
                        "price_snapshot_id": price_snapshot_id,
                        "market_date": point.market_date.isoformat(),
                    }
                )
            except (PriceUnavailableError, ValueError) as exc:
                errors.append(f"{order['symbol']}: {exc}")
        # A portfolio plan is one unit. If one required price is missing, retain
        # every order as PENDING so a retry cannot create a partial allocation.
        if errors:
            return PendingExecutionResult((), tuple(errors))
        executed_at = max(item["market_date"] for item in executions) + "T09:30:00"
        fills = self.repository.execute_orders_atomically(
            account_id,
            executions,
            slippage_bps=self.slippage_bps,
            executed_at=executed_at,
        )
        return PendingExecutionResult(fills, ())

    def build_and_store_plan(self, account_id: int, run_id: int) -> AllocationPlan:
        balance = self.repository.get_balance(account_id)
        positions = tuple(
            PositionState(
                symbol=position.symbol,
                quantity=nanos_to_quantity(position.quantity_nanos),
                market_price=micros_to_money(position.last_price_micros),
            )
            for position in self.repository.get_positions(account_id)
        )
        decisions = self.repository.get_decisions(run_id)
        allocation_decisions = tuple(
            AllocationDecision(
                symbol=decision.symbol,
                rating=decision.rating.title(),
                price=micros_to_money(decision.reference_price_micros or 0),
                confidence=micros_to_money(decision.conviction_micros or 0),
            )
            for decision in decisions
            if decision.status == "COMPLETED"
        )
        plan = build_allocation_plan(
            cash=balance,
            positions=positions,
            decisions=allocation_decisions,
            policy=self.policy,
        )
        decisions_by_symbol = {decision.symbol: decision for decision in decisions}
        for planned in plan.orders:
            decision = decisions_by_symbol[planned.symbol]
            self.repository.create_order(
                decision.id,
                account_id,
                client_order_key=f"run:{run_id}:{planned.symbol}",
                symbol=planned.symbol,
                side=planned.side.value if planned.side else None,
                quantity=(planned.quantity if planned.side and planned.side.value == "SELL" else None),
                notional=(planned.notional if planned.side and planned.side.value == "BUY" else None),
                scheduled_for=decision.analysis_date,
                status=("PENDING" if planned.status.value == "PLANNED" else planned.status.value),
                reason=planned.reason,
                metadata={
                    "decision": planned.decision,
                    "reference_price": str(planned.price),
                    "planned_notional": str(planned.notional),
                },
            )
        self.repository.set_run_status(run_id, "PLANNED")
        return plan

    def snapshot(
        self,
        account_id: int,
        *,
        valuation_date: str,
        source_run_id: int | None = None,
        benchmark_symbol: str | None = None,
    ) -> SnapshotResult:
        prices: dict[str, tuple[object, str]] = {}
        errors: list[str] = []
        for position in self.repository.get_positions(account_id):
            try:
                point = fetch_valuation_close(
                    position.symbol,
                    valuation_date=valuation_date,
                    loader=self.price_loader,
                )
                prices[position.symbol] = (point.price, point.market_date.isoformat())
                self.repository.record_price(
                    position.symbol,
                    purpose="VALUATION",
                    field="CLOSE",
                    price=point.price,
                    market_date=point.market_date.isoformat(),
                )
            except (PriceUnavailableError, ValueError) as exc:
                errors.append(f"{position.symbol}: {exc}")
        if errors:
            return SnapshotResult(0, tuple(errors))

        benchmark_price = None
        if benchmark_symbol:
            try:
                point = fetch_valuation_close(
                    benchmark_symbol,
                    valuation_date=valuation_date,
                    loader=self.price_loader,
                )
                benchmark_price = point.price
                self.repository.record_price(
                    benchmark_symbol,
                    purpose="BENCHMARK",
                    field="CLOSE",
                    price=point.price,
                    market_date=point.market_date.isoformat(),
                )
            except (PriceUnavailableError, ValueError) as exc:
                errors.append(f"benchmark {benchmark_symbol}: {exc}")

        snapshot_id = self.repository.record_snapshot(
            account_id,
            snapshot_date=valuation_date,
            prices=prices,
            source_run_id=source_run_id,
            benchmark_price=benchmark_price,
        )
        return SnapshotResult(snapshot_id, tuple(errors))


__all__ = ["PendingExecutionResult", "PersistentPaperService", "SnapshotResult"]
