"""Deterministic long-only paper-trading account tests."""

import json

import pytest

from tradingagents.paper_trading import PaperPortfolio


@pytest.mark.unit
def test_account_starts_with_configured_cash(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)

    snapshot = portfolio.snapshot()

    assert snapshot.cash == pytest.approx(1_000)
    assert snapshot.total_equity == pytest.approx(1_000)
    assert snapshot.positions == ()


@pytest.mark.unit
def test_buy_targets_twenty_percent_and_uses_fractional_shares(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)

    result = portfolio.apply_decision(
        symbol="AAPL",
        trade_date="2026-08-25",
        decision_text="**Rating**: Buy",
        price=125,
    )

    snapshot = portfolio.snapshot()
    assert result.side == "BUY"
    assert result.quantity == pytest.approx(1.6)
    assert snapshot.cash == pytest.approx(800)
    assert snapshot.positions[0].market_value == pytest.approx(200)


@pytest.mark.unit
def test_overweight_adds_ten_percent_but_never_exceeds_cap(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)

    first = portfolio.apply_decision(
        symbol="NVDA",
        trade_date="2026-08-25",
        decision_text="Rating: Overweight",
        price=100,
    )
    second = portfolio.apply_decision(
        symbol="NVDA",
        trade_date="2026-08-26",
        decision_text="Rating: Overweight",
        price=100,
    )
    third = portfolio.apply_decision(
        symbol="NVDA",
        trade_date="2026-08-27",
        decision_text="Rating: Overweight",
        price=100,
    )

    assert first.quantity == pytest.approx(1)
    assert second.quantity == pytest.approx(1)
    assert third.side == "HOLD"
    assert portfolio.snapshot().positions[0].market_value == pytest.approx(200)


@pytest.mark.unit
def test_underweight_sells_half_and_sell_closes_position(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)
    portfolio.apply_decision(
        symbol="AAPL",
        trade_date="2026-08-25",
        decision_text="Rating: Buy",
        price=100,
    )

    trim = portfolio.apply_decision(
        symbol="AAPL",
        trade_date="2026-08-26",
        decision_text="Rating: Underweight",
        price=120,
    )
    close = portfolio.apply_decision(
        symbol="AAPL",
        trade_date="2026-08-27",
        decision_text="Rating: Sell",
        price=110,
    )

    snapshot = portfolio.snapshot()
    assert trim.side == "SELL"
    assert trim.quantity == pytest.approx(1)
    assert close.side == "SELL"
    assert close.quantity == pytest.approx(1)
    assert snapshot.positions == ()
    assert snapshot.cash == pytest.approx(1_030)
    assert snapshot.realized_pnl == pytest.approx(30)


@pytest.mark.unit
def test_same_symbol_and_date_cannot_execute_twice(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)
    first = portfolio.apply_decision(
        symbol="BTCUSD",
        trade_date="2026-08-25",
        decision_text="Rating: Buy",
        price=100_000,
    )
    second = portfolio.apply_decision(
        symbol="BTC-USD",
        trade_date="2026-08-25",
        decision_text="Rating: Buy",
        price=100_000,
    )

    assert first.duplicate is False
    assert second.duplicate is True
    assert portfolio.snapshot().cash == pytest.approx(800)


@pytest.mark.unit
def test_hold_records_decision_without_changing_cash(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)

    result = portfolio.apply_decision(
        symbol="MSFT",
        trade_date="2026-08-25",
        decision_text="Rating: Hold",
        price=500,
    )

    assert result.side == "HOLD"
    assert portfolio.snapshot().cash == pytest.approx(1_000)


@pytest.mark.unit
def test_snapshot_can_be_exported_as_json(tmp_path):
    portfolio = PaperPortfolio(tmp_path / "portfolio.db", initial_cash=1_000)
    output = portfolio.write_snapshot(tmp_path / "paper_portfolio.json")

    data = json.loads(output.read_text())
    assert data["initial_cash"] == 1_000
    assert data["total_equity"] == 1_000
    assert data["positions"] == []
