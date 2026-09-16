"""Select paper storage without putting database credentials in analysis configs."""

import os
from pathlib import Path

from tradingagents.paper.database import PaperDatabase


def configured_database(sqlite_path: str | Path):
    backend = os.getenv("DB_CONNECTION", "mysql" if os.getenv("DB_HOST") else "sqlite").lower()
    if backend == "sqlite":
        return PaperDatabase(sqlite_path)
    if backend != "mysql":
        raise ValueError("DB_CONNECTION must be mysql or sqlite")
    from tradingagents.paper.mysql import MySQLDatabase

    return MySQLDatabase.from_env()
