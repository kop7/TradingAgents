"""Startup workflow selection and paper-trading watchlist dispatch."""

from types import SimpleNamespace
from unittest import mock

import pytest

import cli.main as cli_main
from cli.models import AnalystType


def test_waiting_account_does_not_start_new_analysis(capsys):
    account = SimpleNamespace(
        id=1, name="matija", status="ACTIVE", strategy_config_json="{}", benchmark_symbol="URA",
    )
    repo = mock.Mock()
    repo.get_account.return_value = account
    repo.get_balance.return_value = 1000
    service = mock.Mock()
    service.execute_pending.return_value = SimpleNamespace(
        errors=(), fills=(), waiting=("HON: waiting for market Open",),
    )
    with (
        mock.patch.object(cli_main, "PaperRepository", return_value=repo),
        mock.patch.object(cli_main, "PersistentPaperService", return_value=service),
        mock.patch.object(cli_main, "_display_persistent_account"),
        mock.patch.object(cli_main, "_run_selected_analysis") as analyze,
    ):
        cli_main.run_persistent_paper_batch(
            ["HON"], {"analysis_date": "2026-09-15"}, False, account_name="matija",
        )
    analyze.assert_not_called()
    repo.create_run.assert_not_called()
    service.build_and_store_plan.assert_not_called()
    assert "Waiting for market data" in capsys.readouterr().out


def test_account_creation_and_bulk_import_are_idempotent(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tradingagents.paper.repository import PaperRepository

    path = tmp_path / "paper.sqlite"
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(path))
    runner = CliRunner()
    for cash in ("2500", "9999"):
        result = runner.invoke(cli_main.app, [
            "paper", "account-create", "--name", "test", "--cash", cash,
        ])
        assert result.exit_code == 0, result.output
    repo = PaperRepository(path)
    assert repo.get_balance(repo.get_account("test").id) == 2500
    repo.upsert_instrument("UEC")
    repo.set_instrument_paper_enabled("UEC", False)
    tickers = tmp_path / "tickers.txt"
    tickers.write_text("UEC,ccj\nDNN UEC", encoding="utf-8")
    result = runner.invoke(cli_main.app, [
        "paper", "symbols", "add-bulk", "CCJ,NXE", "--file", str(tickers),
    ])
    assert result.exit_code == 0, result.output
    assert "Added: 3. Duplicates skipped: 3." in result.output
    assert [item.symbol for item in repo.list_instruments(active_only=True)] == ["CCJ", "DNN", "NXE"]
    result = runner.invoke(cli_main.app, ["paper", "symbols", "add-bulk", "AAPL,../BAD"])
    assert result.exit_code != 0
    assert "AAPL" not in [item.symbol for item in repo.list_instruments()]


@pytest.mark.parametrize("status", ["PARTIAL_ANALYSIS", "COMPLETED"])
def test_resume_skips_successful_ticker_and_retries_failed_ticker(status):
    account = SimpleNamespace(
        id=1, name="test", status="ACTIVE", strategy_config_json="{}", benchmark_symbol="URA",
    )
    repo = mock.Mock()
    repo.get_or_create_account.return_value = account
    repo.get_balance.return_value = 1000
    repo.create_run.return_value = (SimpleNamespace(id=2, status=status), False)
    repo.get_decisions.return_value = (
        SimpleNamespace(symbol="AAPL", status="COMPLETED"),
        SimpleNamespace(symbol="MSFT", status="FAILED"),
    )
    service = mock.Mock()
    service.execute_pending.return_value = SimpleNamespace(fills=(), errors=(), waiting=())
    service.snapshot.return_value = SimpleNamespace(snapshot_id=1, errors=())
    service.build_and_store_plan.return_value = SimpleNamespace(orders=(), projected_cash=1000)
    with (
        mock.patch.object(cli_main, "PaperRepository", return_value=repo),
        mock.patch.object(cli_main, "PersistentPaperService", return_value=service),
        mock.patch.object(cli_main, "_display_persistent_account"),
        mock.patch.object(cli_main, "_run_selected_analysis", side_effect=ConnectionError("offline")) as analyze,
    ):
        cli_main.run_persistent_paper_batch(
            ["AAPL", "MSFT"], {"analysis_date": "2026-01-02", "analysts": []}, False,
        )
    assert analyze.call_count == 1
    assert analyze.call_args.args[0]["ticker"] == "MSFT"
    repo.set_run_status.assert_any_call(2, "PARTIAL_ANALYSIS", "offline")


def test_database_workflow_skips_ticker_prompt(tmp_path, monkeypatch):
    from tradingagents.paper.repository import PaperRepository

    path = tmp_path / "paper.sqlite"
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(path))
    repo = PaperRepository(path)
    repo.upsert_instrument("MSFT")
    repo.upsert_instrument("AAPL")
    repo.set_instrument_paper_enabled("MSFT", False)
    with (
        mock.patch.object(cli_main, "select_workflow_mode", return_value="paper_trading_db"),
        mock.patch.object(cli_main, "select_paper_accounts", return_value=["default"]),
        mock.patch.object(cli_main, "get_paper_watchlist") as prompt,
        mock.patch.object(cli_main, "get_user_selections", return_value={}) as settings,
        mock.patch.object(cli_main, "run_persistent_paper_batch") as batch,
    ):
        cli_main.run_analysis(checkpoint=False)
    prompt.assert_not_called()
    settings.assert_called_once_with(selected_ticker="AAPL")
    batch.assert_called_once_with(["AAPL"], {}, False, account_name="default")


def test_database_workflow_empty_list_exits_before_settings(tmp_path, monkeypatch):
    import typer

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(tmp_path / "empty.sqlite"))
    with (
        mock.patch.object(cli_main, "select_workflow_mode", return_value="paper_trading_db"),
        mock.patch.object(cli_main, "get_user_selections") as settings,
        pytest.raises(typer.Exit),
    ):
        cli_main.run_analysis()
    settings.assert_not_called()


def test_ticker_management_commands(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tradingagents.paper.repository import PaperRepository

    path = tmp_path / "paper.sqlite"
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(path))
    runner = CliRunner()
    for args in (
        ["add", "aapl", "MSFT"], ["pause", "AAPL"], ["resume", "AAPL"],
        ["disable", "MSFT"], ["enable", "MSFT"], ["list"],
    ):
        result = runner.invoke(cli_main.app, ["paper", "symbols", *args])
        assert result.exit_code == 0, result.output
    assert len(PaperRepository(path).list_instruments(active_only=True)) == 2
    result = runner.invoke(cli_main.app, ["paper", "symbols", "add", "../BAD"])
    assert result.exit_code != 0


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
        mock.patch.object(cli_main, "select_paper_accounts", return_value=["default"]),
        mock.patch.object(
            cli_main, "get_paper_watchlist", return_value=["AAPL", "MSFT", "BTC-USD"]
        ),
        mock.patch.object(cli_main, "get_user_selections", return_value=shared) as settings,
        mock.patch.object(cli_main, "run_persistent_paper_batch") as run_batch,
    ):
        cli_main.run_analysis(checkpoint=False)

    settings.assert_called_once_with(selected_ticker="AAPL")
    run_batch.assert_called_once_with(
        ["AAPL", "MSFT", "BTC-USD"], shared, False, account_name="default",
    )


@pytest.mark.parametrize("workflow", ["paper_trading", "paper_trading_db"])
def test_paper_dispatches_each_selected_account(workflow):
    with (
        mock.patch.object(cli_main, "select_workflow_mode", return_value=workflow),
        mock.patch.object(cli_main, "get_paper_watchlist", return_value=["UEC"]),
        mock.patch.object(cli_main, "get_paper_database_watchlist", return_value=["UEC"]),
        mock.patch.object(cli_main, "select_paper_accounts", return_value=["first", "second"]) as select,
        mock.patch.object(cli_main, "get_user_selections", return_value={}),
        mock.patch.object(cli_main, "run_persistent_paper_batch") as batch,
    ):
        cli_main.run_analysis(checkpoint=False)
    select.assert_called_once()
    assert batch.call_args_list == [
        mock.call(["UEC"], {}, False, account_name="first"),
        mock.call(["UEC"], {}, False, account_name="second"),
    ]


def test_account_selector_shows_only_active_accounts_and_balances(tmp_path, monkeypatch):
    from tradingagents.paper.repository import PaperRepository

    path = tmp_path / "accounts.sqlite"
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(path))
    repo = PaperRepository(path)
    repo.create_account("first", 2500)
    repo.create_account("second", 100)
    repo.create_account("paused", 900)
    with repo.database.transaction() as connection:
        connection.execute("UPDATE accounts SET status = 'PAUSED' WHERE name = 'paused'")
    with mock.patch.object(cli_main.questionary, "checkbox") as checkbox:
        checkbox.return_value.ask.return_value = ["first", "second"]
        assert cli_main.select_paper_accounts() == ["first", "second"]
    choices = checkbox.call_args.kwargs["choices"]
    assert [choice.value for choice in choices] == ["first", "second"]
    assert "2,500.00 USD" in choices[0].title


def test_account_selector_empty_database_exits(tmp_path, monkeypatch):
    import typer

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "paper_db_path", str(tmp_path / "empty.sqlite"))
    with mock.patch.object(cli_main.questionary, "checkbox") as checkbox, pytest.raises(typer.Exit):
        cli_main.select_paper_accounts()
    checkbox.assert_not_called()


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
    service.execute_pending.return_value = SimpleNamespace(fills=(), errors=(), waiting=())
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
