"""Repository-facing executor for deterministic paper allocation plans.

All durability and transaction boundaries belong to the repository.  In
particular, ``apply_orders_atomically`` must validate the account version and
commit account cash, positions, fills, and cash-ledger entries together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from tradingagents.paper.allocator import AllocationPlan, OrderSide, PlanStatus


@dataclass(frozen=True)
class ExecutionOrder:
    symbol: str
    decision: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    notional: Decimal
    reason: str


@dataclass(frozen=True)
class ExecutionCommand:
    account_id: str
    run_id: str
    idempotency_key: str
    expected_account_version: int
    expected_starting_cash: Decimal
    orders: tuple[ExecutionOrder, ...]
    executed_at: datetime


@dataclass(frozen=True)
class ExecutionFill:
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    notional: Decimal


@dataclass(frozen=True)
class ExecutionReceipt:
    account_id: str
    run_id: str
    idempotency_key: str
    account_version: int
    cash_after: Decimal
    fills: tuple[ExecutionFill, ...]
    duplicate: bool = False


@runtime_checkable
class ExecutionRepository(Protocol):
    """Minimal persistence contract required by :class:`PaperExecutor`."""

    def get_execution(self, idempotency_key: str) -> ExecutionReceipt | None:
        """Return a prior committed receipt, if this command already ran."""
        ...

    def apply_orders_atomically(self, command: ExecutionCommand) -> ExecutionReceipt:
        """Commit all fills/account/position/ledger changes or none of them."""
        ...


class PaperExecutor:
    def __init__(self, repository: ExecutionRepository):
        self.repository = repository

    def execute(
        self,
        *,
        account_id: str,
        run_id: str,
        plan: AllocationPlan,
        expected_account_version: int,
        idempotency_key: str,
        executed_at: datetime | None = None,
    ) -> ExecutionReceipt:
        """Execute one immutable plan through the repository exactly once."""
        if not account_id.strip():
            raise ValueError("account_id must not be empty")
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if expected_account_version < 0:
            raise ValueError("expected_account_version must not be negative")

        existing = self.repository.get_execution(idempotency_key)
        if existing is not None:
            return ExecutionReceipt(
                account_id=existing.account_id,
                run_id=existing.run_id,
                idempotency_key=existing.idempotency_key,
                account_version=existing.account_version,
                cash_after=existing.cash_after,
                fills=existing.fills,
                duplicate=True,
            )

        orders = tuple(
            ExecutionOrder(
                symbol=order.symbol,
                decision=order.decision,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                notional=order.notional,
                reason=order.reason,
            )
            for order in plan.orders
            if order.status is PlanStatus.PLANNED and order.side is not None
        )
        self._validate_orders(orders)

        command = ExecutionCommand(
            account_id=account_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            expected_account_version=expected_account_version,
            expected_starting_cash=plan.starting_cash,
            orders=orders,
            executed_at=executed_at or datetime.now(UTC),
        )
        return self.repository.apply_orders_atomically(command)

    @staticmethod
    def _validate_orders(orders: tuple[ExecutionOrder, ...]) -> None:
        seen_buy = False
        for order in orders:
            if order.quantity <= 0 or order.price <= 0 or order.notional <= 0:
                raise ValueError("executable orders require positive quantity, price, and notional")
            if order.quantity * order.price != order.notional:
                raise ValueError("order notional must equal quantity multiplied by price")
            if order.side is OrderSide.BUY:
                seen_buy = True
            elif seen_buy:
                raise ValueError("all SELL orders must precede BUY orders")
