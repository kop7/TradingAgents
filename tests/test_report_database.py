"""Report text, migration and historical import regression tests."""

import pytest
from typer.testing import CliRunner

from tradingagents.paper.repository import PaperRepository
from tradingagents.reporting import render_reports, write_report_tree


def bundle():
    return {
        "market_report": "# Tržište\n**Žuti signal**",
        "sentiment_report": "Sentiment", "news_report": "News",
        "fundamentals_report": "Fundamentals", "trader_investment_plan": "Trader",
        "investment_debate_state": {
            "bull_history": "Bull", "bear_history": "Bear", "judge_decision": "Research",
        },
        "risk_debate_state": {
            "aggressive_history": "Aggressive", "conservative_history": "Conservative",
            "neutral_history": "Neutral", "judge_decision": "Portfolio",
        },
    }


def check_reports(repo):
    account = repo.create_account("reports", 100)
    run, _ = repo.create_run(
        account.id, run_key="reports", analysis_date="2026-01-02", symbols=["UEC"],
    )
    reports = render_reports(bundle(), "UEC")
    assert len(reports) == 13
    for _ in range(2):
        repo.save_reports("UEC", "2026-01-02", reports, run_id=run.id)
    repo.save_reports("UEC", "2026-01-02", {"empty": "  "}, run_id=run.id)
    with repo.connect() as connection:
        rows = connection.execute("SELECT * FROM analysis_reports").fetchall()
        assert len(rows) == 13
        assert {row["report_type"]: row["content_markdown"] for row in rows} == reports
        assert all(row["run_id"] == run.id and row["instrument_id"] for row in rows)
    repo.save_reports("UEC", "2026-01-02", reports, execution_key="single:one")
    repo.save_reports("UEC", "2026-01-02", reports, execution_key="single:two")
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_reports").fetchone()[0] == 39
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    with pytest.raises(ValueError):
        repo.save_reports("UEC", "2026-01-03", reports, run_id=run.id)


def test_report_bundle_persistence(tmp_path):
    check_reports(PaperRepository(tmp_path / "reports.sqlite"))


def test_import_reports_is_repeatable(tmp_path, monkeypatch):
    from cli.main import app
    from tradingagents.default_config import DEFAULT_CONFIG

    path = tmp_path / "reports.sqlite"
    monkeypatch.setitem(DEFAULT_CONFIG, "paper_db_path", str(path))
    repo = PaperRepository(path)
    account = repo.create_account("legacy", 100)
    run, _ = repo.create_run(
        account.id, run_key="legacy", analysis_date="2026-01-02", symbols=["UEC"],
    )
    report = write_report_tree(bundle(), "UEC", tmp_path / "files")
    repo.save_decision(run.id, symbol="UEC", analysis_date="2026-01-02", rating="HOLD",
                       raw_decision_text="Hold", report_path=str(report))
    for count in (13, 0):
        result = CliRunner().invoke(app, ["db", "import-reports"])
        assert result.exit_code == 0, result.output
        assert f"Imported reports: {count}." in result.output


def test_v3_upgrade_preserves_account_and_adds_reports(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    repo = PaperRepository(path)
    repo.create_account("existing", 123)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE analysis_reports")
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")
        connection.execute("PRAGMA user_version = 3")
    repo = PaperRepository(path)
    repo.database.initialize()
    assert repo.get_balance(repo.get_account("existing").id) == 123
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_reports").fetchone()[0] == 0
