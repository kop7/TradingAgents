"""Explicit database migration command."""

import typer

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.paper.connection import configured_database
from tradingagents.paper.database import SCHEMA_VERSION, PaperDatabase

database_app = typer.Typer(help="Database schema migrations using DB_* environment settings.")


@database_app.command("import-reports")
def import_reports():
    """Import existing Markdown files referenced by paper decisions, without rerunning analyses."""
    from pathlib import Path

    from tradingagents.paper.repository import PaperRepository

    paths = (
        "1_analysts/market.md", "1_analysts/sentiment.md", "1_analysts/news.md",
        "1_analysts/fundamentals.md", "2_research/bull.md", "2_research/bear.md",
        "2_research/manager.md", "3_trading/trader.md", "4_risk/aggressive.md",
        "4_risk/conservative.md", "4_risk/neutral.md", "5_portfolio/decision.md",
        "complete_report.md",
    )
    repo = PaperRepository(configured_database(DEFAULT_CONFIG["paper_db_path"]))
    with repo.connect() as connection:
        decisions = connection.execute(
            "SELECT run_id, symbol, analysis_date, report_path FROM decisions "
            "WHERE report_path IS NOT NULL ORDER BY id"
        ).fetchall()
    imported = missing = 0
    for row in decisions:
        directory = Path(row["report_path"]).parent
        reports = {}
        for relative in paths:
            file = directory / relative
            if file.is_file():
                reports[relative] = file.read_text(encoding="utf-8")
        if not reports:
            missing += 1
            continue
        # Never overwrite reports already persisted by a new analysis.
        with repo.connect() as connection:
            existing = {item[0] for item in connection.execute(
                "SELECT report_type FROM analysis_reports ar JOIN instruments i "
                "ON i.id = ar.instrument_id WHERE ar.run_id = ? AND i.symbol = ?",
                (row["run_id"], row["symbol"]),
            )}
        reports = {key: value for key, value in reports.items() if key not in existing}
        repo.save_reports(row["symbol"], row["analysis_date"], reports, run_id=row["run_id"])
        imported += sum(bool(value.strip()) for value in reports.values())
    typer.echo(f"Imported reports: {imported}. Decisions with no accessible files: {missing}.")


@database_app.command("migrate")
def migrate():
    try:
        database = configured_database(DEFAULT_CONFIG["paper_db_path"])
        if isinstance(database, PaperDatabase):
            database.initialize()
            backend = "SQLite"
        else:
            database.migrate()
            backend = "MySQL"
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    except Exception as exc:
        # Connection exceptions may include credentials; keep CLI output sanitized.
        typer.echo(
            f"Migration failed ({type(exc).__name__}). Check DB_* settings, "
            "database access and migration privileges.", err=True,
        )
        raise typer.Exit(code=1) from None
    typer.echo(f"{backend} migrations complete. Schema version: {SCHEMA_VERSION}.")
