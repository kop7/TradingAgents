"""Startup workflow selection and paper-trading watchlist dispatch."""

from types import SimpleNamespace
from unittest import mock

import pytest

import cli.main as cli_main
from cli.models import AnalystType


@pytest.mark.unit
def test_parse_watchlist_accepts_many_symbols_and_preserves_order():
    raw = "AAPL, MSFT NVDA\nAMZN, META, GOOGL, TSLA, JPM, V, COST"

    assert cli_main.parse_watchlist(raw) == [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "TSLA",
        "JPM",
        "V",
        "COST",
    ]


@pytest.mark.unit
def test_parse_watchlist_normalizes_and_deduplicates_symbols():
    assert cli_main.parse_watchlist("btcusd, BTC-USD, xauusd") == [
        "BTC-USD",
        "GC=F",
    ]


@pytest.mark.unit
def test_parse_watchlist_rejects_invalid_symbols():
    with pytest.raises(ValueError, match="Invalid ticker"):
        cli_main.parse_watchlist("AAPL, ../BAD")


@pytest.mark.unit
def test_original_analysis_flow_disables_paper_trading():
    selections = {"ticker": "AAPL"}

    with (
        mock.patch.object(cli_main, "select_workflow_mode", return_value="analysis"),
        mock.patch.object(cli_main, "get_user_selections", return_value=selections),
        mock.patch.object(cli_main, "_run_selected_analysis") as run_one,
    ):
        cli_main.run_analysis(checkpoint=True)

    run_one.assert_called_once_with(
        selections,
        checkpoint=True,
        paper_trading=False,
        prompt_for_report=True,
    )


@pytest.mark.unit
def test_paper_flow_dispatches_one_persistent_watchlist_batch():
    shared = {
        "ticker": "AAPL",
        "asset_type": "stock",
        "analysts": [AnalystType.MARKET, AnalystType.FUNDAMENTALS],
    }

    with (
        mock.patch.object(cli_main, "select_workflow_mode", return_value="paper_trading"),
        mock.patch.object(
            cli_main, "get_paper_watchlist", return_value=["AAPL", "MSFT", "BTC-USD"]
        ),
        mock.patch.object(cli_main, "get_user_selections", return_value=shared) as settings,
        mock.patch.object(cli_main, "run_persistent_paper_batch") as run_batch,
    ):
        cli_main.run_analysis(checkpoint=False)

    settings.assert_called_once_with(selected_ticker="AAPL")
    run_batch.assert_called_once_with(["AAPL", "MSFT", "BTC-USD"], shared, False)


@pytest.mark.unit
def test_all_connection_failures_stop_without_creating_orders_or_raising():
    shared = {
        "ticker": "UEC",
        "analysis_date": "2026-08-26",
        "asset_type": "stock",
        "analysts": [AnalystType.MARKET],
    }
    account = SimpleNamespace(
        id=1,
        name="default",
        status="ACTIVE",
        strategy_config_json="{}",
        benchmark_symbol="URA",
    )
    run = SimpleNamespace(id=2, status="CREATED")
    repo = mock.Mock()
    repo.get_or_create_account.return_value = account
    repo.get_balance.return_value = 1000
    repo.create_run.return_value = (run, True)
    repo.get_decisions.side_effect = [(), (SimpleNamespace(status="FAILED"),)]
    service = mock.Mock()
    service.execute_pending.return_value = SimpleNamespace(fills=(), errors=())
    service.snapshot.return_value = SimpleNamespace(snapshot_id=1, errors=())

    with (
        mock.patch.object(cli_main, "PaperRepository", return_value=repo),
        mock.patch.object(cli_main, "PersistentPaperService", return_value=service),
        mock.patch.object(
            cli_main, "_run_selected_analysis", side_effect=ConnectionError("Connection error")
        ),
        mock.patch.object(cli_main, "_display_persistent_account"),
    ):
        cli_main.run_persistent_paper_batch(["UEC"], shared, checkpoint=False)

    service.build_and_store_plan.assert_not_called()
    repo.set_run_status.assert_any_call(2, "FAILED", "No ticker analysis completed")
