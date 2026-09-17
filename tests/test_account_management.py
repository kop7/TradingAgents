"""Account edits and deposits use isolated databases, never the configured account."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from tradingagents.paper.repository import PaperRepository

SETTINGS = {
    "buy_notional": 90, "overweight_notional": 10, "cash_reserve_pct": 0.1,
    "max_position_pct": 0.2, "slippage_bps": 5,
}


@pytest.fixture
def repo(tmp_path):
    repository = PaperRepository(tmp_path / "accounts.sqlite")
    repository.create_account("first", 1000, strategy_config={"extra": "preserved", **SETTINGS})
    repository.create_account("second", 200)
    return repository


def test_settings_merge_isolation_and_stale_form(repo):
    account = repo.get_account("first")
    repo.update_account_settings(account.id, {**SETTINGS, "buy_notional": 25},
                                 expected_revision=account.state_revision)
    updated = repo.get_account(account.id)
    assert json.loads(updated.strategy_config_json) == {"extra": "preserved", **SETTINGS,
                                                        "buy_notional": 25}
    assert updated.state_revision == account.state_revision + 1
    assert repo.get_account("second").strategy_config_json == "{}"
    assert repo.get_balance(account.id) == Decimal(1000)
    with pytest.raises(ValueError, match="međuvremenu"):
        repo.update_account_settings(account.id, SETTINGS, expected_revision=account.state_revision)


@pytest.mark.parametrize(("key", "value"), [
    ("buy_notional", 0), ("buy_notional", "NaN"), ("buy_notional", "Infinity"),
    ("buy_notional", "1e30"), ("overweight_notional", -1),
    ("cash_reserve_pct", 1.1), ("max_position_pct", 0), ("max_position_pct", 2),
    ("slippage_bps", -1), ("slippage_bps", 10000),
])
def test_invalid_settings_do_not_write(repo, key, value):
    account = repo.get_account("first")
    with pytest.raises(ValueError):
        repo.update_account_settings(account.id, {**SETTINGS, key: value}, expected_revision=0)
    assert repo.get_account(account.id) == account


def test_deposit_idempotence_decimal_ledger_and_contributions(repo):
    account = repo.get_account("first")
    repo.record_snapshot(account.id, snapshot_date="2026-01-01", prices={})
    before = dict(repo.latest_snapshot(account.id))
    assert repo.deposit_cash(account.id, "100.12", idempotency_key="one") == Decimal("1100.12")
    assert repo.deposit_cash(account.id, "100.12", idempotency_key="one") == Decimal("1100.12")
    assert repo.get_account(account.id).state_revision == 1
    assert repo.get_balance(repo.get_account("second").id) == Decimal(200)
    with repo.connect() as connection:
        ledger = connection.execute("SELECT * FROM cash_ledger WHERE account_id=? ORDER BY id",
                                     [account.id]).fetchall()
    assert [row["entry_type"] for row in ledger] == ["INITIAL_FUNDING", "DEPOSIT"]
    assert ledger[1]["amount_micros"] == 100120000
    assert dict(repo.latest_snapshot(account.id)) == before
    repo.record_snapshot(account.id, snapshot_date="2026-01-02", prices={})
    from tradingagents.paper.statistics import equity_curve

    with repo.connect() as connection:
        curve = equity_curve(connection, account.id)
    assert curve[-1].net_contributions == Decimal("1100.12")
    assert curve[-1].cumulative_return == 0
    with pytest.raises(ValueError, match="drugoj uplati"):
        repo.deposit_cash(account.id, 999, idempotency_key="one")
    assert repo.get_balance(account.id) == Decimal("1100.12")


@pytest.mark.parametrize("amount", [0, -10, "NaN", "Infinity", "0.0000001", "1e30"])
def test_invalid_deposit_does_not_write(repo, amount):
    with pytest.raises(ValueError):
        repo.deposit_cash(repo.get_account("first").id, amount, idempotency_key="bad")
    assert repo.get_balance(repo.get_account("first").id) == Decimal(1000)


def test_busy_closed_and_missing_accounts(repo):
    account = repo.get_account("first")
    run, _ = repo.create_run(account.id, run_key="busy", analysis_date="2026-01-01", symbols=[])
    for status in ("CREATED", "ANALYZING", "PARTIAL_ANALYSIS", "PLANNED", "EXECUTING"):
        repo.set_run_status(run.id, status)
        with pytest.raises(ValueError, match="nedovršen"):
            repo.deposit_cash(account.id, 100, idempotency_key="busy")
        with pytest.raises(ValueError, match="nedovršen"):
            repo.update_account_settings(account.id, SETTINGS, expected_revision=0)
    repo.set_run_status(run.id, "COMPLETED")
    with repo.database.transaction() as connection:
        connection.execute("UPDATE accounts SET status='CLOSED' WHERE id=?", [account.id])
    with pytest.raises(ValueError, match="Zatvoreni"):
        repo.deposit_cash(account.id, 100, idempotency_key="closed")
    with pytest.raises(LookupError):
        repo.deposit_cash(99999, 100, idempotency_key="missing")


def test_deposit_rollback_and_concurrent_retry(repo):
    account = repo.get_account("first")
    with repo.connect() as connection:
        connection.execute("CREATE TRIGGER fail_revision BEFORE UPDATE ON accounts "
                           "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
    with pytest.raises(Exception, match="simulated failure"):
        repo.deposit_cash(account.id, 100, idempotency_key="rollback")
    assert repo.get_balance(account.id) == Decimal(1000)
    with repo.connect() as connection:
        connection.execute("DROP TRIGGER fail_revision")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: repo.deposit_cash(account.id, "0.01", idempotency_key="parallel"), range(2),
        ))
    assert results == [Decimal("1000.01"), Decimal("1000.01")]
    assert repo.get_account(account.id).state_revision == 1


def test_pending_order_blocks_both_forms(repo):
    account = repo.get_account("first")
    run, _ = repo.create_run(account.id, run_key="pending", analysis_date="2026-01-01",
                             symbols=["AAPL"])
    decision = repo.save_decision(run.id, symbol="AAPL", analysis_date="2026-01-01",
                                  rating="BUY", raw_decision_text="BUY")
    repo.create_order(decision.id, account.id, client_order_key="pending", symbol="AAPL",
                       side="BUY", notional=20)
    repo.set_run_status(run.id, "COMPLETED")
    with pytest.raises(ValueError, match="PENDING"):
        repo.deposit_cash(account.id, 100, idempotency_key="pending")
    with pytest.raises(ValueError, match="PENDING"):
        repo.update_account_settings(account.id, SETTINGS, expected_revision=0)
    assert repo.get_balance(account.id) == 1000


def test_settings_and_deposit_forms(repo, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from tradingagents.cockpit import app, settings

    account = repo.get_account("first")
    monkeypatch.setattr(app, "read_connection", repo.connect)
    monkeypatch.setattr(settings, "writable_repository", lambda: repo)
    app.st.cache_data.clear()
    ui = AppTest.from_string(
        "from tradingagents.cockpit.settings import account_settings\n"
        "from tradingagents.cockpit.app import load\n"
        f"account_settings({account.id}, load)\n"
    ).run()
    assert not ui.exception and not ui.error
    next(w for w in ui.number_input if w.label.startswith("BUY iznos")).set_value(75.0)
    next(w for w in ui.button if w.label == "Spremi postavke").click().run()
    assert not ui.error and not ui.exception
    assert json.loads(repo.get_account(account.id).strategy_config_json)["buy_notional"] == 75
    real_deposit = repo.deposit_cash
    attempts = []

    def uncertain_deposit(*args, **kwargs):
        attempts.append(kwargs["idempotency_key"])
        result = real_deposit(*args, **kwargs)
        if len(attempts) == 1:
            raise TimeoutError("connection lost after commit")
        return result

    monkeypatch.setattr(repo, "deposit_cash", uncertain_deposit)
    ui.text_input[0].set_value("100,12")
    next(w for w in ui.button if w.label == "Uplati").click().run()
    assert ui.error
    ui.run()
    assert ui.text_input[0].disabled
    next(w for w in ui.button if w.label == "Ponovi uplatu").click().run()
    assert not ui.error and not ui.exception
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert repo.get_balance(account.id) == Decimal("1100.12")
    assert any(w.label == "Nova uplata" for w in ui.button)
    ui.run()
    assert repo.get_balance(account.id) == Decimal("1100.12")
