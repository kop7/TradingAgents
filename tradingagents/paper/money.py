"""Exact storage conversions for the paper-trading database.

Public APIs accept dollar/share values as ``Decimal``, strings, or integers and
persist fixed-scale integers. Floats are accepted at the boundary for
compatibility, but are converted through ``str`` instead of their binary value.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import TypeAlias

DecimalInput: TypeAlias = Decimal | str | int | float

MONEY_SCALE = 1_000_000
QUANTITY_SCALE = 1_000_000_000

_MONEY_SCALE_DECIMAL = Decimal(MONEY_SCALE)
_QUANTITY_SCALE_DECIMAL = Decimal(QUANTITY_SCALE)
_INTEGER_QUANTUM = Decimal("1")


def as_decimal(value: DecimalInput, *, field: str = "value") -> Decimal:
    """Return a finite Decimal without inheriting binary-float noise."""
    if isinstance(value, bool):
        raise TypeError(f"{field} must be a number, not bool")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def money_to_micros(value: DecimalInput, *, field: str = "money") -> int:
    """Convert a dollar amount to integer micro-dollars using banker's rounding."""
    decimal_value = as_decimal(value, field=field)
    return int(
        (decimal_value * _MONEY_SCALE_DECIMAL).quantize(
            _INTEGER_QUANTUM, rounding=ROUND_HALF_EVEN
        )
    )


def micros_to_money(value: int) -> Decimal:
    """Convert integer micro-dollars to an exact dollar Decimal."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("micro-dollar value must be an integer")
    return Decimal(value) / _MONEY_SCALE_DECIMAL


def quantity_to_nanos(value: DecimalInput, *, field: str = "quantity") -> int:
    """Convert a share quantity to integer nano-units."""
    decimal_value = as_decimal(value, field=field)
    return int(
        (decimal_value * _QUANTITY_SCALE_DECIMAL).quantize(
            _INTEGER_QUANTUM, rounding=ROUND_HALF_EVEN
        )
    )


def nanos_to_quantity(value: int) -> Decimal:
    """Convert integer nano-units to an exact share Decimal."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("nano-quantity value must be an integer")
    return Decimal(value) / _QUANTITY_SCALE_DECIMAL


def notional_micros(price_micros: int, quantity_nanos: int) -> int:
    """Calculate a rounded notional from scaled integer price and quantity."""
    if price_micros < 0:
        raise ValueError("price_micros cannot be negative")
    if quantity_nanos < 0:
        raise ValueError("quantity_nanos cannot be negative")
    value = Decimal(price_micros) * Decimal(quantity_nanos) / _QUANTITY_SCALE_DECIMAL
    return int(value.quantize(_INTEGER_QUANTUM, rounding=ROUND_HALF_EVEN))


def signed_notional_micros(price_delta_micros: int, quantity_nanos: int) -> int:
    """Calculate signed P&L from a price delta and a non-negative quantity."""
    if quantity_nanos < 0:
        raise ValueError("quantity_nanos cannot be negative")
    value = (
        Decimal(price_delta_micros)
        * Decimal(quantity_nanos)
        / _QUANTITY_SCALE_DECIMAL
    )
    return int(value.quantize(_INTEGER_QUANTUM, rounding=ROUND_HALF_EVEN))


def weighted_price_micros(
    existing_quantity_nanos: int,
    existing_price_micros: int,
    added_quantity_nanos: int,
    added_cost_micros: int,
) -> int:
    """Return weighted average unit cost from existing units and added total cost."""
    total_quantity = existing_quantity_nanos + added_quantity_nanos
    if total_quantity <= 0:
        raise ValueError("total quantity must be positive")
    existing_cost = notional_micros(existing_price_micros, existing_quantity_nanos)
    price = (
        Decimal(existing_cost + added_cost_micros)
        * _QUANTITY_SCALE_DECIMAL
        / Decimal(total_quantity)
    )
    return int(price.quantize(_INTEGER_QUANTUM, rounding=ROUND_HALF_EVEN))
