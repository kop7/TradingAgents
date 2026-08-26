"""Focused tests for the persistent v2 paper-trading account."""

from decimal import Decimal

import pandas as pd
import pytest

from tradingagents.paper.allocator import (
    AllocationDecision,
    AllocationPolicy,
    PositionState,
    build_allocation_plan,
)
from tradingagents.paper.exports import export_account
from tradingagents.paper.prices import first_open_after_decision, valuation_close
from tradingagents.paper.repository import PaperRepository
from tradingagents.paper.service import PersistentPaperService
from tradingagents.paper.statistics import portfolio_summary


def _prices(*_args):
    return pd.DataFrame(
        {
            "Date": ["2026-01-02", "2026-01-05", "2026-01-06"],
            "Open": [Decimal("10"), Decimal("11"), Decimal("8")],
            "Close": [Decimal("10.5"), Decimal("12"), Decimal("8.5")],
        }
    )


@pytest.mark.unit
def test_price_selection_uses_next_open_and_latest_close():
    next_open = first_open_after_decision(
        _prices(), decision_date="2026-01-02", as_of_date="2026-01-06"
    )
    close = valuation_close(_prices(), valuation_date="2026-01-05")

    assert (next_open.market_date.isoformat(), next_open.price) == (
        "2026-01-05",
        Decimal("11"),
    )
    assert (close.market_date.isoformat(), close.price) == (
        "2026-01-05",
        Decimal("12"),
    )


@pytest.mark.unit
def test_allocator_is_order_independent_and_sells_before_buys():
    inputs = [
        AllocationDecision("DNN", "Buy", Decimal("2")),
        AllocationDecision("CCJ", "Sell", Decimal("50")),
        AllocationDecision("UEC", "Hold", Decimal("7")),
    ]
    positions = [PositionState("CCJ", Decimal("1"), Decimal("50"))]
    policy = AllocationPolicy(cash_reserve_pct="0", max_position_pct="1")

    first = build_allocation_plan(
        cash="100", positions=positions, decisions=inputs, policy=policy
    )
    second = build_allocation_plan(
        cash="100", positions=positions, decisions=reversed(inputs), policy=policy
    )

    assert first == second
    assert [(item.symbol, item.side.value if item.side else None) for item in first.orders] == [
        ("CCJ", "SELL"),
        ("UEC", None),
        ("DNN", "BUY"),
    ]


@pytest.mark.unit
def test_account_ledger_orders_and_d1_fill_are_persistent(tmp_path):
    repo = PaperRepository(tmp_path / "paper.sqlite")
    account = repo.create_account("uranium", "100")
    run, created = repo.create_run(
        account.id,
        run_key="daily:2026-01-02",
        analysis_date="2026-01-02",
        symbols=["CCJ"],
    )
    assert created is True
    repo.save_decision(
        run.id,
        symbol="CCJ",
        analysis_date="2026-01-02",
        rating="BUY",
        raw_decision_text="Rating: Buy",
        reference_price="10.5",
        price_as_of="2026-01-02",
    )
    service = PersistentPaperService(
        repo,
        policy=AllocationPolicy(cash_reserve_pct="0", max_position_pct="1"),
        slippage_bps=0,
        price_loader=_prices,
    )

    plan = service.build_and_store_plan(account.id, run.id)
    assert plan.projected_cash == Decimal("80")
    assert service.execute_pending(account.id, as_of_date="2026-01-02").fills == ()

    execution = service.execute_pending(account.id, as_of_date="2026-01-05")
    assert execution.errors == ()
    assert len(execution.fills) == 1
    assert repo.get_balance(account.id) == Decimal("80")
    assert repo.get_positions(account.id)[0].symbol == "CCJ"

    # Retrying the same date is idempotent and cannot charge the account twice.
    assert service.execute_pending(account.id, as_of_date="2026-01-05").fills == ()
    assert repo.get_balance(account.id) == Decimal("80")
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM cash_ledger").fetchone()[0] == 2


@pytest.mark.unit
def test_sell_at_a_loss_records_negative_realized_pnl(tmp_path):
    repo = PaperRepository(tmp_path / "paper.sqlite")
    account = repo.create_account("loss-test", 100)

    buy_run, _ = repo.create_run(
        account.id, run_key="buy", analysis_date="2026-01-02", symbols=["CCJ"]
    )
    buy_decision = repo.save_decision(
        buy_run.id,
        symbol="CCJ",
        analysis_date="2026-01-02",
        rating="BUY",
        raw_decision_text="Buy",
        reference_price=10,
    )
    buy = repo.create_order(
        buy_decision.id,
        account.id,
        client_order_key="buy",
        symbol="CCJ",
        side="BUY",
        notional=20,
    )
    repo.execute_orders_atomically(
        account.id, [{"order_id": buy.id, "side": "BUY", "raw_price": 10}]
    )

    sell_run, _ = repo.create_run(
        account.id, run_key="sell", analysis_date="2026-01-05", symbols=["CCJ"]
    )
    sell_decision = repo.save_decision(
        sell_run.id,
        symbol="CCJ",
        analysis_date="2026-01-05",
        rating="SELL",
        raw_decision_text="Sell",
        reference_price=8,
    )
    sell = repo.create_order(
        sell_decision.id,
        account.id,
        client_order_key="sell",
        symbol="CCJ",
        side="SELL",
        quantity=2,
    )
    fill = repo.execute_orders_atomically(
        account.id, [{"order_id": sell.id, "side": "SELL", "raw_price": 8}]
    )[0]

    assert fill.realized_pnl_micros == -4_000_000
    assert repo.get_balance(account.id) == Decimal("96")
    assert repo.get_positions(account.id) == ()


@pytest.mark.unit
def test_snapshots_statistics_and_exports_are_queryable(tmp_path):
    repo = PaperRepository(tmp_path / "paper.sqlite")
    account = repo.create_account("stats", 100)
    repo.record_snapshot(
        account.id,
        snapshot_date="2026-01-02",
        prices={},
        benchmark_price=10,
    )
    repo.record_snapshot(
        account.id,
        snapshot_date="2026-01-05",
        prices={},
        benchmark_price=11,
    )

    with repo.connect() as connection:
        summary = portfolio_summary(connection, str(account.id))
        output = export_account(connection, account.id, tmp_path / "export")

    assert summary.trading_days == 2
    assert summary.end_equity == Decimal("100")
    assert summary.benchmark_return == Decimal("0.1")
    assert (output / "account_summary.json").exists()
    assert (output / "daily_portfolio.csv").exists()
    assert (output / "cash_ledger.csv").exists()
