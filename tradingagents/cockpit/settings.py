"""Explicit account writes, kept out of cached read queries."""

import json
import os
from uuid import uuid4

import streamlit as st

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.paper.account_settings import SETTING_KEYS, positive_amount_micros
from tradingagents.paper.money import micros_to_money
from tradingagents.paper.mysql import MySQLDatabase
from tradingagents.paper.repository import PaperRepository


def writable_repository():
    if os.getenv("DB_CONNECTION", "mysql").lower() != "mysql":
        raise ValueError("Cockpit zahtijeva DB_CONNECTION=mysql.")
    return PaperRepository(MySQLDatabase.from_env())


def account_settings(account_id, load):
    snapshot_key = f"account_edit:{account_id}"
    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = load("account_details", account_id)
    account = st.session_state[snapshot_key]
    currency = account["currency"]
    st.caption(f"Račun: {account['name']} · {currency}. Datumski i ticker filtri ovdje se ne primjenjuju.")
    st.metric("Cash računa", f"{micros_to_money(int(account['cash_micros'])):,.2f} {currency}")
    st.caption("Cash uključuje uplate. Overview i grafovi prikazuju zadnju spremljenu valuaciju; "
               "uplata ne mijenja povijesne valuacije.")
    if account["status"] == "CLOSED":
        st.info("Račun je zatvoren; izmjene nisu dostupne.")
        return
    flash_key = f"account_message:{account_id}"
    if flash_key in st.session_state:
        st.success(st.session_state.pop(flash_key))
    config = json.loads(account["strategy_config_json"] or "{}")
    current = {key: config.get(key, DEFAULT_CONFIG[f"paper_{key}"]) for key in SETTING_KEYS}
    st.subheader("Pravila kupnje")
    st.caption("Postavke koristi sljedeće pokretanje TradingAgents procesa. "
               "Završi aktivnu obradu i pokreni novi CLI nakon spremanja.")
    with st.form(f"settings:{account_id}:{account['state_revision']}"):
        buy = st.number_input(f"BUY iznos ({currency})", min_value=0.01,
                              value=float(current["buy_notional"]), step=10.0)
        overweight = st.number_input(f"OVERWEIGHT iznos ({currency})", min_value=0.01,
                                     value=float(current["overweight_notional"]), step=5.0)
        reserve = st.number_input("Cash rezerva (%)", min_value=0.0, max_value=100.0,
                                  value=float(current["cash_reserve_pct"]) * 100, step=1.0)
        maximum = st.number_input("Maksimalni udio tickera (%)", min_value=0.01, max_value=100.0,
                                  value=float(current["max_position_pct"]) * 100, step=1.0)
        slip = st.number_input("Slippage (bps; 5 bps = 0,05%)", min_value=0.0, max_value=9999.0,
                               value=float(current["slippage_bps"]), step=1.0)
        save = st.form_submit_button("Spremi postavke")
    if save:
        try:
            writable_repository().update_account_settings(account_id, {
                "buy_notional": buy, "overweight_notional": overweight,
                "cash_reserve_pct": reserve / 100, "max_position_pct": maximum / 100,
                "slippage_bps": slip,
            }, expected_revision=int(account["state_revision"]))
        except (ValueError, LookupError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Spremanje nije potvrđeno. Provjeri vezu i DB prava te osvježi prikaz.")
        else:
            load.clear()
            del st.session_state[snapshot_key]
            st.session_state[flash_key] = "Postavke računa su spremljene."
            st.rerun()

    st.subheader("Dodaj virtualni novac")
    request_key = f"deposit_request:{account_id}"
    if request_key not in st.session_state:
        st.session_state[request_key] = {"key": str(uuid4()), "amount": None, "done": False}
    request = st.session_state[request_key]
    if request["done"]:
        st.success(f"Uplata od {request['amount']} {currency} je evidentirana.")
        if st.button("Nova uplata", key=f"new_deposit:{account_id}"):
            del st.session_state[request_key]
            st.rerun()
    else:
        with st.form(f"deposit:{account_id}:{request['key']}"):
            amount = st.text_input(f"Iznos uplate ({currency}, npr. 100.00)",
                                   value=request["amount"] or "100.00",
                                   disabled=request["amount"] is not None)
            submit = st.form_submit_button("Uplati" if request["amount"] is None else "Ponovi uplatu")
        if submit:
            try:
                if request["amount"] is None:
                    amount = amount.strip().replace(",", ".")
                    positive_amount_micros(amount)
                    request["amount"] = amount
                writable_repository().deposit_cash(
                    account_id, request["amount"], idempotency_key=request["key"],
                )
            except (ValueError, LookupError) as exc:
                request["amount"] = None
                st.error(str(exc))
            except Exception:
                st.error("Uplata nije potvrđena. Ponovi istu uplatu: isti zahtjev neće dvaput "
                         "povećati saldo. Provjeri vezu i DB prava.")
            else:
                request["done"] = True
                load.clear()
                st.session_state.pop(snapshot_key, None)
                st.rerun()
    deposits = load("deposits", account_id)
    if deposits:
        st.caption("Posljednjih 20 uplata")
        st.dataframe([{
            "Vrijeme": row["occurred_at"],
            f"Uplata ({currency})": str(micros_to_money(int(row["amount_micros"]))),
            f"Cash nakon uplate ({currency})": str(micros_to_money(int(row["balance_after_micros"]))),
        } for row in deposits], hide_index=True)
