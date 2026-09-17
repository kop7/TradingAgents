"""MySQL integration checks use a disposable database and explicit TEST_MYSQL_* settings."""

import os
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from tradingagents.paper.mysql import MySQLDatabase
from tradingagents.paper.repository import PaperRepository


@pytest.mark.integration
@pytest.mark.parametrize("scenario", [
    "test_settings_merge_isolation_and_stale_form",
    "test_deposit_idempotence_decimal_ledger_and_contributions",
    "test_busy_closed_and_missing_accounts",
    "test_pending_order_blocks_both_forms",
])
def test_account_management_on_mysql(mysql_database, scenario):
    from tests import test_account_management as cases

    mysql_database.migrate()
    repo = PaperRepository(mysql_database)
    repo.create_account("first", 1000, strategy_config={"extra": "preserved", **cases.SETTINGS})
    repo.create_account("second", 200)
    getattr(cases, scenario)(repo)


@pytest.fixture
def mysql_database():
    if not os.getenv("TEST_MYSQL_HOST"):
        pytest.skip("Set TEST_MYSQL_HOST to a disposable MySQL server")
    pymysql = pytest.importorskip("pymysql")
    settings = {
        "host": os.environ["TEST_MYSQL_HOST"], "port": int(os.getenv("TEST_MYSQL_PORT", "3306")),
        "user": os.getenv("TEST_MYSQL_USER", "root"),
        "password": os.getenv("TEST_MYSQL_PASSWORD", ""),
    }
    name = "paper_test_" + uuid4().hex
    with pymysql.connect(**settings, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {name}")
        try:
            yield MySQLDatabase(**settings, database=name)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE {name}")


@pytest.mark.integration
@pytest.mark.parametrize("scenario", [
    "test_ticker_registry_links_decisions_without_reenabling_tickers",
    "test_account_ledger_orders_and_d1_fill_are_persistent",
    "test_sell_at_a_loss_records_negative_realized_pnl",
    "test_snapshots_statistics_and_exports_are_queryable",
])
def test_paper_scenarios_on_mysql(mysql_database, monkeypatch, tmp_path, scenario):
    from tests import test_persistent_paper as cases

    mysql_database.migrate()
    mysql_database.migrate()
    repo = PaperRepository(mysql_database)
    monkeypatch.setattr(cases, "PaperRepository", lambda _: repo)
    getattr(cases, scenario)(tmp_path)


@pytest.mark.integration
def test_mysql_migration_command_and_constraints(mysql_database, monkeypatch):
    import pymysql

    import cli.database as command
    from cli.main import app

    with pytest.raises(RuntimeError, match="db migrate"):
        mysql_database.initialize()
    monkeypatch.setattr(command, "configured_database", lambda _: mysql_database)
    for _ in range(2):
        result = CliRunner().invoke(app, ["db", "migrate"])
        assert result.exit_code == 0, result.output
        assert "MySQL migrations complete" in result.output
    repo = PaperRepository(mysql_database)
    account = repo.create_account("constraints", 100)
    with pytest.raises(pymysql.MySQLError, match="append-only"), repo.connect() as connection:
        connection.execute("UPDATE cash_ledger SET note = 'changed'")
    with pytest.raises(pymysql.MySQLError, match="append-only"), repo.connect() as connection:
        connection.execute("DELETE FROM cash_ledger")
    run, _ = repo.create_run(
        account.id, run_key="constraints", analysis_date="2026-01-02", symbols=["AAPL"],
    )
    decision = repo.save_decision(
        run.id, symbol="AAPL", analysis_date="2026-01-02", rating="HOLD", raw_decision_text="Hold",
    )
    with pytest.raises(pymysql.IntegrityError), repo.connect() as connection:
        connection.execute("UPDATE decisions SET instrument_id = 999999 WHERE id = ?", (decision.id,))
    with pytest.raises(ValueError, match="rollback"), mysql_database.transaction() as connection:
        connection.execute("UPDATE instruments SET status = 'PAUSED'")
        raise ValueError("rollback")
    assert repo.list_instruments(active_only=True)[0].symbol == "AAPL"


def test_database_settings_keep_password_out_of_config(monkeypatch):
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.paper.connection import configured_database

    for key, value in {
        "DB_CONNECTION": "mysql", "DB_HOST": "localhost", "DB_PORT": "3307",
        "DB_DATABASE": "test", "DB_USERNAME": "test", "DB_PASSWORD": "private-test-password",
    }.items():
        monkeypatch.setenv(key, value)
    db = configured_database("unused.sqlite")
    assert isinstance(db, MySQLDatabase)
    assert db.settings["port"] == 3307
    assert "private-test-password" not in str(DEFAULT_CONFIG)
    monkeypatch.setenv("DB_PORT", "not-a-port")
    with pytest.raises(ValueError, match="DB_PORT"):
        configured_database("unused.sqlite")


@pytest.mark.integration
def test_mysql_concurrent_execution_charges_only_once(mysql_database):
    from concurrent.futures import ThreadPoolExecutor

    mysql_database.migrate()
    repo = PaperRepository(mysql_database)
    account = repo.create_account("concurrent", 100)
    run, _ = repo.create_run(
        account.id, run_key="buy", analysis_date="2026-01-02", symbols=["AAPL"],
    )
    decision = repo.save_decision(
        run.id, symbol="AAPL", analysis_date="2026-01-02", rating="BUY", raw_decision_text="Buy",
    )
    order = repo.create_order(
        decision.id, account.id, client_order_key="buy", symbol="AAPL", side="BUY", notional=20,
    )

    def execute():
        return repo.execute_orders_atomically(
            account.id, [{"order_id": order.id, "side": "BUY", "raw_price": 10}],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(execute), pool.submit(execute)]]
    assert len({fill.id for result in results for fill in result}) == 1
    assert repo.get_balance(account.id) == 80
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1


def test_sqlite_migration_command(tmp_path, monkeypatch):
    import cli.database as command
    from cli.main import app

    monkeypatch.setitem(command.DEFAULT_CONFIG, "paper_db_path", str(tmp_path / "paper.sqlite"))
    result = CliRunner().invoke(app, ["db", "migrate"])
    assert result.exit_code == 0, result.output
    assert "SQLite migrations complete" in result.output


@pytest.mark.integration
def test_mysql_report_migration(mysql_database):
    from tests.test_report_database import bundle
    from tradingagents.paper.mysql_schema import MIGRATIONS
    from tradingagents.reporting import render_reports

    # Seed a real v3 database and verify v4 only adds report storage.
    mysql_database.migrate()
    repo = PaperRepository(mysql_database)
    existing = repo.create_account("existing", 123)
    with mysql_database.connect() as connection:
        connection.execute("DROP TABLE analysis_reports")
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")
    assert MIGRATIONS[-1][0] == 4
    mysql_database.migrate()
    mysql_database.migrate()
    assert repo.get_balance(existing.id) == 123
    # Bundle check expects only its own account.
    check_repo = PaperRepository(mysql_database)
    check_repo.save_reports("UEC", "2026-01-02", render_reports(bundle(), "UEC"),
                            execution_key="single:test")
    with check_repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_reports").fetchone()[0] == 13
