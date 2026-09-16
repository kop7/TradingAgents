"""Deterministic portfolio allocation for persistent paper trading.

The allocator is deliberately pure: it does not fetch prices and it does not
write to the database.  Given the same account state, decisions, and policy it
always emits the same ordered plan, regardless of watchlist input order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")
ONE = Decimal("1")


def _decimal(value: Decimal | int | float | str) -> Decimal:
    """Convert external numeric input without inheriting binary-float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _symbol(value: str) -> str:
    canonical = value.strip().upper()
    if not canonical:
        raise ValueError("symbol must not be empty")
    return canonical


class PlanStatus(str, Enum):
    PLANNED = "PLANNED"
    NOOP = "NOOP"
    REJECTED = "REJECTED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class PositionState:
    symbol: str
    quantity: Decimal
    market_price: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        object.__setattr__(self, "market_price", _decimal(self.market_price))
        if self.quantity < ZERO:
            raise ValueError("position quantity must not be negative")
        if self.market_price <= ZERO:
            raise ValueError("position market_price must be greater than zero")

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.market_price


@dataclass(frozen=True)
class AllocationDecision:
    symbol: str
    rating: str
    price: Decimal
    confidence: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "rating", self.rating.strip().title())
        object.__setattr__(self, "price", _decimal(self.price))
        object.__setattr__(self, "confidence", _decimal(self.confidence))


@dataclass(frozen=True)
class AllocationPolicy:
    fixed_buy_amount: Decimal = Decimal("20")
    fixed_overweight_amount: Decimal = Decimal("10")
    max_position_pct: Decimal = Decimal("0.20")
    cash_reserve_pct: Decimal = ZERO
    minimum_cash_reserve: Decimal = ZERO

    def __post_init__(self) -> None:
        for field_name in (
            "fixed_buy_amount",
            "fixed_overweight_amount",
            "max_position_pct",
            "cash_reserve_pct",
            "minimum_cash_reserve",
        ):
            object.__setattr__(self, field_name, _decimal(getattr(self, field_name)))
        if self.fixed_buy_amount <= ZERO:
            raise ValueError("fixed_buy_amount must be greater than zero")
        if self.fixed_overweight_amount <= ZERO:
            raise ValueError("fixed_overweight_amount must be greater than zero")
        if not ZERO < self.max_position_pct <= ONE:
            raise ValueError("max_position_pct must be between zero and one")
        if not ZERO <= self.cash_reserve_pct <= ONE:
            raise ValueError("cash_reserve_pct must be between zero and one")
        if self.minimum_cash_reserve < ZERO:
            raise ValueError("minimum_cash_reserve must not be negative")


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    decision: str
    status: PlanStatus
    side: OrderSide | None
    quantity: Decimal
    price: Decimal
    notional: Decimal
    reason: str


@dataclass(frozen=True)
class AllocationPlan:
    starting_cash: Decimal
    starting_equity: Decimal
    required_cash_reserve: Decimal
    projected_cash: Decimal
    orders: tuple[PlannedOrder, ...]

    @property
    def executable_orders(self) -> tuple[PlannedOrder, ...]:
        return tuple(order for order in self.orders if order.status is PlanStatus.PLANNED)


_VALID_RATINGS = {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
_SELL_RANK = {"Sell": 0, "Underweight": 1}
_BUY_RANK = {"Buy": 0, "Overweight": 1}


def _order(
    decision: AllocationDecision,
    *,
    status: PlanStatus,
    side: OrderSide | None = None,
    quantity: Decimal = ZERO,
    notional: Decimal = ZERO,
    reason: str,
) -> PlannedOrder:
    return PlannedOrder(
        symbol=decision.symbol,
        decision=decision.rating,
        status=status,
        side=side,
        quantity=quantity,
        price=decision.price,
        notional=notional,
        reason=reason,
    )


def build_allocation_plan(
    *,
    cash: Decimal | int | float | str,
    positions: Iterable[PositionState],
    decisions: Iterable[AllocationDecision],
    policy: AllocationPolicy | None = None,
) -> AllocationPlan:
    """Build a sells-first, order-independent allocation plan.

    ``NOOP`` means no trade is required (for example Hold or an already-full
    position). ``REJECTED`` means a requested trade cannot pass input or cash
    policy checks. Fractional quantities are intentionally supported.
    """
    selected_policy = policy or AllocationPolicy()
    starting_cash = _decimal(cash)
    if starting_cash < ZERO:
        raise ValueError("cash must not be negative")

    position_list = tuple(positions)
    position_map = {position.symbol: position for position in position_list}
    if len(position_map) != len(position_list):
        raise ValueError("positions must contain each symbol at most once")

    decision_list = tuple(decisions)
    decision_map = {decision.symbol: decision for decision in decision_list}
    if len(decision_map) != len(decision_list):
        raise ValueError("decisions must contain each symbol at most once")

    starting_equity = starting_cash + sum(
        (position.market_value for position in position_list), start=ZERO
    )
    reserve = max(
        selected_policy.minimum_cash_reserve,
        starting_equity * selected_policy.cash_reserve_pct,
    )
    projected_cash = starting_cash
    projected_quantities = {
        symbol: position.quantity for symbol, position in position_map.items()
    }
    planned: list[PlannedOrder] = []

    invalid = sorted(
        (decision for decision in decision_list if decision.rating not in _VALID_RATINGS),
        key=lambda item: item.symbol,
    )
    for decision in invalid:
        planned.append(
            _order(
                decision,
                status=PlanStatus.REJECTED,
                reason=f"Unsupported portfolio rating: {decision.rating or '<empty>'}.",
            )
        )

    sell_decisions = sorted(
        (decision for decision in decision_list if decision.rating in _SELL_RANK),
        key=lambda item: (_SELL_RANK[item.rating], item.symbol),
    )
    for decision in sell_decisions:
        position = position_map.get(decision.symbol)
        current_quantity = projected_quantities.get(decision.symbol, ZERO)
        if decision.price <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.REJECTED,
                    reason="A positive execution price is required.",
                )
            )
        elif position is None or current_quantity <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.NOOP,
                    reason="There is no open position to reduce.",
                )
            )
        else:
            quantity = current_quantity if decision.rating == "Sell" else current_quantity / 2
            notional = quantity * decision.price
            projected_quantities[decision.symbol] = current_quantity - quantity
            projected_cash += notional
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.PLANNED,
                    side=OrderSide.SELL,
                    quantity=quantity,
                    notional=notional,
                    reason=(
                        "Sell closes the full position."
                        if decision.rating == "Sell"
                        else "Underweight reduces the position by half."
                    ),
                )
            )

    hold_decisions = sorted(
        (decision for decision in decision_list if decision.rating == "Hold"),
        key=lambda item: item.symbol,
    )
    for decision in hold_decisions:
        planned.append(
            _order(
                decision,
                status=PlanStatus.NOOP,
                reason="Hold requires no portfolio change.",
            )
        )

    buy_decisions = sorted(
        (decision for decision in decision_list if decision.rating in _BUY_RANK),
        key=lambda item: (_BUY_RANK[item.rating], -item.confidence, item.symbol),
    )
    position_cap = starting_equity * selected_policy.max_position_pct
    for decision in buy_decisions:
        if decision.price <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.REJECTED,
                    reason="A positive execution price is required.",
                )
            )
            continue

        current_quantity = projected_quantities.get(decision.symbol, ZERO)
        current_value = current_quantity * decision.price
        capacity = max(ZERO, position_cap - current_value)
        if capacity <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.NOOP,
                    reason="Position is already at the configured maximum.",
                )
            )
            continue

        spendable_cash = max(ZERO, projected_cash - reserve)
        if spendable_cash <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.REJECTED,
                    reason="Cash reserve policy leaves no spendable cash.",
                )
            )
            continue

        requested = (
            selected_policy.fixed_buy_amount
            if decision.rating == "Buy"
            else selected_policy.fixed_overweight_amount
        )
        notional = min(requested, capacity, spendable_cash)
        if notional <= ZERO:
            planned.append(
                _order(
                    decision,
                    status=PlanStatus.REJECTED,
                    reason="The requested purchase has no executable notional.",
                )
            )
            continue

        quantity = notional / decision.price
        projected_quantities[decision.symbol] = current_quantity + quantity
        projected_cash -= notional
        planned.append(
            _order(
                decision,
                status=PlanStatus.PLANNED,
                side=OrderSide.BUY,
                quantity=quantity,
                notional=notional,
                reason=(
                    f"{decision.rating} allocates {notional} while respecting "
                    "the position cap and cash reserve."
                ),
            )
        )

    return AllocationPlan(
        starting_cash=starting_cash,
        starting_equity=starting_equity,
        required_cash_reserve=reserve,
        projected_cash=projected_cash,
        orders=tuple(planned),
    )
