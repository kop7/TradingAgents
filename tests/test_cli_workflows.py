"""Startup workflow selection and paper-trading watchlist dispatch."""

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
def test_paper_flow_runs_every_watchlist_symbol_with_shared_settings():
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
        mock.patch.object(cli_main, "_run_selected_analysis") as run_one,
    ):
        cli_main.run_analysis(checkpoint=False)

    settings.assert_called_once_with(selected_ticker="AAPL")
    assert run_one.call_count == 3

    first = run_one.call_args_list[0]
    second = run_one.call_args_list[1]
    crypto = run_one.call_args_list[2]
    assert first.args[0]["ticker"] == "AAPL"
    assert second.args[0]["ticker"] == "MSFT"
    assert crypto.args[0]["ticker"] == "BTC-USD"
    assert crypto.args[0]["asset_type"] == "crypto"
    assert crypto.args[0]["analysts"] == [AnalystType.MARKET]
    for call in run_one.call_args_list:
        assert call.kwargs == {
            "checkpoint": False,
            "paper_trading": True,
            "prompt_for_report": False,
        }
