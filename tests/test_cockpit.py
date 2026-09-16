"""Read-only queries against isolated storage; no live DB or vendors."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from tradingagents.cockpit.data import CockpitData, Filters, read_connection
from tradingagents.paper.repository import PaperRepository


@pytest.fixture
def data(tmp_path):
    repo = PaperRepository(tmp_path / "cockpit.sqlite")
    a = repo.create_account("one", 100)
    b = repo.create_account("two", 100)
    for account in (a, b):
        run, _ = repo.create_run(account.id, run_key="run", analysis_date="2026-01-02",
                                 symbols=["AAPL"])
        repo.save_reports("AAPL", "2026-01-02", {"complete_report.md": account.name},
                          run_id=run.id)
    repo.save_reports("AAPL", "2026-01-02", {"complete_report.md": "single"},
                      execution_key="single:one")
    with repo.connect() as connection:
        yield CockpitData(connection), a.id, b.id


def test_report_scope_lazy_content_and_filters(data):
    query, a, b = data
    fa = Filters(a, "2026-01-01", "2026-01-03")
    ra = query.reports(fa)
    rb = query.reports(Filters(b, fa.start, fa.end))
    assert len(ra) == len(rb) == 1
    assert "content_markdown" not in ra[0]
    assert query.reports(fa, report_id=ra[0]["id"])[0]["content_markdown"] == "one"
    assert query.reports(fa, report_id=rb[0]["id"]) == []
    single = query.reports(Filters(None, fa.start, fa.end))
    assert len(single) == 1 and single[0]["run_id"] is None
    assert query.reports(Filters(a, fa.start, fa.end, "' OR 1=1 --")) == []
    assert query.reports(Filters(a, "2027-01-01", "2027-01-02")) == []
    assert query.reports(Filters(a, fa.start, fa.end, status="FAILED")) == []


def test_runs_scope_requested_tickers_pagination(data):
    query, a, b = data
    filters = Filters(a, "2026-01-01", "2026-01-03", "AAPL")
    runs = query.runs(filters)
    assert len(runs) == 1
    assert runs[0]["completed_tickers"] == 0
    assert query.runs(filters, page=1, size=1) == []
    assert query.runs(Filters(a, filters.start, filters.end, "%")) == []
    assert query.runs(Filters(a, filters.start, filters.end, status="FAILED")) == []
    assert query.decisions(b, runs[0]["id"]) == []
    assert query.curve(filters) == ()


def test_curve_cash_flows_and_account_isolation(data):
    query, a, b = data
    for account, day, equity, contribution in [
        (a, "2026-01-01", 100, 100), (a, "2026-01-02", 210, 200),
        (a, "2026-01-03", 189, 200), (b, "2026-01-02", 999, 100),
    ]:
        query.connection.execute(
            "INSERT INTO portfolio_daily_snapshots (account_id, snapshot_date, state_revision, "
            "cash_micros, market_value_micros, total_equity_micros, realized_pnl_micros, "
            "unrealized_pnl_micros, net_contributions_micros, captured_at) "
            "VALUES (?, ?, 0, 0, ?, ?, 0, 0, ?, ?)",
            [account, day, equity * 1000000, equity * 1000000, contribution * 1000000, day],
        )
    curve = query.curve(Filters(a, "2026-01-02", "2026-01-03"))
    assert len(curve) == 2
    assert curve[0].cumulative_return == Decimal("0.1")
    assert curve[-1].drawdown == Decimal("-0.1")
    assert curve[-1].total_equity == Decimal(189)
    assert curve[0].net_contributions == Decimal(200)
    assert all(point.benchmark_return is None for point in curve)
    query.connection.execute(
        "UPDATE portfolio_daily_snapshots SET benchmark_value_micros=100000000 "
        "WHERE account_id=? AND snapshot_date='2026-01-01'", [a],
    )
    query.connection.execute(
        "UPDATE portfolio_daily_snapshots SET benchmark_value_micros=105000000 "
        "WHERE account_id=? AND snapshot_date='2026-01-02'", [a],
    )
    curve = query.curve(Filters(a, "2026-01-02", "2026-01-03"))
    assert curve[0].benchmark_return == Decimal("0.05")
    assert curve[-1].benchmark_return is None
    for account, day, pnl in [(a, "2026-01-02", -3000000),
                               (a, "2026-01-03", 9000000), (b, "2026-01-02", 999000000)]:
        snapshot = query.rows("SELECT id FROM portfolio_daily_snapshots "
                              "WHERE account_id=? AND snapshot_date=?", [account, day])[0]
        query.connection.execute(
            "INSERT INTO position_daily_snapshots (portfolio_snapshot_id, symbol, "
            "quantity_nanos, average_cost_micros, close_price_micros, price_as_of, "
            "market_value_micros, unrealized_pnl_micros) VALUES (?, 'AAPL', "
            "1000000000, 100000000, 97000000, ?, 97000000, ?)",
            [snapshot["id"], day, pnl],
        )
    tickers = query.ticker_pnl(Filters(a, "2026-01-01", "2026-01-02"))
    assert len(tickers) == 1
    assert tickers[0].unrealized_pnl == Decimal(-3)
    assert tickers[0].realized_pnl == Decimal(0)


def test_mysql_read_only_transaction(monkeypatch):
    monkeypatch.setenv("DB_CONNECTION", "mysql")
    connection = MagicMock()
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr("tradingagents.cockpit.data.MySQLDatabase.from_env", lambda: database)
    with read_connection() as actual:
        assert actual is connection
    assert [call.args[0] for call in connection.execute.call_args_list] == [
        "SET TRANSACTION READ ONLY", "START TRANSACTION WITH CONSISTENT SNAPSHOT",
    ]
    database.initialize.assert_not_called()


def test_invalid_range():
    with pytest.raises(ValueError):
        Filters(1, "2026-02-01", "2026-01-01")


def test_ui_empty_and_error_states(monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from tradingagents.cockpit import app

    monkeypatch.setattr(CockpitData, "accounts", lambda self: [])
    monkeypatch.setattr(CockpitData, "reports", lambda *args: [])
    connection = MagicMock()
    monkeypatch.setattr(app, "read_connection", lambda: connection)
    # The script executes in its own module, so patch its imported connection factory.
    monkeypatch.setattr("tradingagents.cockpit.data.read_connection", lambda: connection)
    app.st.cache_data.clear()
    ui = AppTest.from_file(str(Path(app.__file__))).run()
    assert not ui.exception
    assert not ui.error
    assert "Nema spremljenih" in ui.info[0].value
    ui.sidebar.date_input[0].set_value(date.today() + timedelta(days=1)).run()
    assert "Početni datum" in ui.error[0].value


def test_launcher_uses_localhost(monkeypatch):
    from tradingagents.cockpit import launcher

    monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda name: object())
    call = MagicMock(return_value=0)
    monkeypatch.setattr(launcher.subprocess, "call", call)
    assert launcher.launch() == 0
    assert "--server.address=127.0.0.1" in call.call_args.args[0]
    assert "--server.port=8501" in call.call_args.args[0]


def test_ui_overview_and_report_selection(monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path
    from types import SimpleNamespace

    from streamlit.testing.v1 import AppTest

    from tradingagents.cockpit import app

    calls = []

    def reports(self, filters, page=0, size=25, report_id=None):
        calls.append(report_id)
        row = {"id": 7, "symbol": "AAPL", "analysis_date": date.today().isoformat(),
               "execution_key": "test", "run_id": 1, "report_type": "complete_report.md"}
        if report_id is not None:
            row["content_markdown"] = "# Test izvještaj"
        return [row]

    point = SimpleNamespace(snapshot_date=date.today().isoformat(), cash=Decimal(100),
                            total_equity=Decimal(110), realized_pnl=Decimal(2),
                            unrealized_pnl=Decimal(8), cumulative_return=Decimal("0.1"),
                            drawdown=Decimal(0), net_contributions=Decimal(100),
                            benchmark_return=None)
    monkeypatch.setattr(CockpitData, "accounts", lambda self: [
        {"id": 1, "name": "Test račun", "currency": "USD", "status": "ACTIVE"},
    ])
    monkeypatch.setattr(CockpitData, "curve", lambda *args: [point])
    monkeypatch.setattr(CockpitData, "valuation_dates", lambda *args: [])
    monkeypatch.setattr(CockpitData, "ticker_pnl", lambda *args: [])
    monkeypatch.setattr(CockpitData, "reports", reports)
    monkeypatch.setattr("tradingagents.cockpit.data.read_connection", MagicMock())
    app.st.cache_data.clear()
    ui = AppTest.from_file(str(Path(app.__file__))).run()
    assert calls == [None]  # No Markdown fetched on initial page load.
    next(widget for widget in ui.selectbox if widget.label == "Izvještaj").select(7).run()
    assert calls[-1] == 7
    assert any("Test izvještaj" in item.value for item in ui.markdown)
    ui.sidebar.selectbox[0].select(1).run()
    ui.sidebar.radio[0].set_value("Overview").run()
    assert not ui.error and not ui.exception
    assert len(ui.metric) == 4
    assert ui.metric[1].value == "110.00 USD"
    assert any("Nema podataka za usporedbu" in item.value for item in ui.info)
    assert any("Nema izvršenja" in item.value for item in ui.info)
    point.benchmark_return = Decimal("0.05")
    monkeypatch.setattr(CockpitData, "ticker_pnl", lambda *args: [
        SimpleNamespace(symbol="AAPL", realized_pnl=Decimal(2), unrealized_pnl=Decimal(-3)),
    ])
    line_chart = MagicMock(wraps=app.st.line_chart)
    bar_chart = MagicMock(wraps=app.st.bar_chart)
    monkeypatch.setattr(app.st, "line_chart", line_chart)
    monkeypatch.setattr(app.st, "bar_chart", bar_chart)
    ui.sidebar.button[0].click().run()
    assert not ui.error and not ui.exception
    assert line_chart.call_count == 3
    assert line_chart.call_args_list[1].args[0]["Neto uplate"].iloc[0] == 100
    assert line_chart.call_args_list[2].args[0]["Benchmark (%)"].iloc[0] == 5
    assert bar_chart.call_args.args[0].loc["AAPL", "Nerealizirani P&L"] == -3
