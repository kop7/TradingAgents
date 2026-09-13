"""Explicit database migration command."""

import typer

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.paper.connection import configured_database
from tradingagents.paper.database import SCHEMA_VERSION, PaperDatabase

database_app = typer.Typer(help="Database schema migrations using DB_* environment settings.")


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
