"""Validation for the editable fixed-notional account policy."""

from tradingagents.paper.allocator import AllocationPolicy
from tradingagents.paper.money import as_decimal, micros_to_money, money_to_micros

SETTING_KEYS = (
    "buy_notional", "overweight_notional", "cash_reserve_pct", "max_position_pct", "slippage_bps",
)


def positive_amount_micros(value):
    number = as_decimal(value, field="Iznos")
    if not 0 < number <= micros_to_money(2**63 - 1):
        raise ValueError("Iznos mora biti pozitivan i unutar podržanog raspona.")
    result = money_to_micros(number)
    if result <= 0:
        raise ValueError("Iznos je manji od podržane preciznosti.")
    return result


def validate_settings(values):
    if set(values) != set(SETTING_KEYS):
        raise ValueError("Potrebno je unijeti svih pet postavki računa.")
    numbers = {key: as_decimal(value, field=key) for key, value in values.items()}
    AllocationPolicy(
        fixed_buy_amount=numbers["buy_notional"],
        fixed_overweight_amount=numbers["overweight_notional"],
        cash_reserve_pct=numbers["cash_reserve_pct"],
        max_position_pct=numbers["max_position_pct"],
    )
    if not 0 <= numbers["slippage_bps"] < 10000:
        raise ValueError("Slippage mora biti od 0 do manje od 10000 bps.")
    for key in ("buy_notional", "overweight_notional"):
        positive_amount_micros(numbers[key])
    return {key: float(value) for key, value in numbers.items()}
