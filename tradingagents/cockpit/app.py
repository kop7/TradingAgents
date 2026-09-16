"""Streamlit entry point, also used directly by the standalone admin image."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from tradingagents.cockpit.data import CockpitData, Filters, read_connection


@st.cache_data(ttl=30, max_entries=256, show_spinner=False)
def load(method, *args):
    with read_connection() as connection:
        return getattr(CockpitData(connection), method)(*args)


def table(rows):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("Nema podataka za odabrane filtre.")


def overview(filters, currency):
    points = load("curve", filters)
    if not points:
        st.info("Nema spremljenih valuacija u razdoblju. Metrike nisu dostupne.")
        return
    last = points[-1]
    st.caption(f"Zadnja spremljena valuacija: {last.snapshot_date} · {currency}")
    if last.snapshot_date < filters.end:
        st.warning("Valuacija je starija od kraja odabranog razdoblja.")
    for column, label, value in zip(st.columns(4),
                                    ["Cash", "Equity", "Realizirani P&L", "Nerealizirani P&L"],
                                    [last.cash, last.total_equity, last.realized_pnl,
                                     last.unrealized_pnl], strict=True):
        column.metric(label, f"{value:,.2f} {currency}")
    st.caption("P&L je kumulativan do datuma valuacije. Prinos i drawdown odnose se na "
               "odabrano razdoblje i korigirani su za novčane tokove.")
    chart = pd.DataFrame([{
        "Datum": p.snapshot_date, "Prinos (%)": float(p.cumulative_return * 100),
        "Drawdown (%)": float(p.drawdown * 100),
    } for p in points]).set_index("Datum")
    st.line_chart(chart)
    st.caption("Prva valuacija je baza ako ne postoji ranija. Cijene se ne dohvaćaju uživo.")
    st.subheader("Equity i neto uplate")
    capital = pd.DataFrame([{
        "Datum": p.snapshot_date, "Equity": float(p.total_equity),
        "Neto uplate": float(p.net_contributions),
    } for p in points]).set_index("Datum")
    st.line_chart(capital, y_label=currency)
    st.caption("Neto uplate su kumulativne uplate umanjene za isplate. "
               "Prikazani su samo datumi sa spremljenom valuacijom.")

    st.subheader("Portfolio i benchmark")
    if any(p.benchmark_return is not None for p in points):
        comparison = pd.DataFrame([{
            "Datum": p.snapshot_date, "Portfolio (%)": float(p.cumulative_return * 100),
            "Benchmark (%)": (float(p.benchmark_return * 100)
                              if p.benchmark_return is not None else None),
        } for p in points]).set_index("Datum")
        st.line_chart(comparison)
        st.caption("Benchmark koristi spremljene vrijednosti i istu početnu valuaciju "
                   "kao prinos portfelja.")
        if any(p.benchmark_return is None for p in points):
            st.warning("Benchmark nedostaje za dio datuma; nedostajuće vrijednosti nisu nule.")
    else:
        st.info("Nema podataka za usporedbu s benchmarkom ili nedostaje njegova početna vrijednost.")

    st.subheader("P&L po tickeru")
    # Use the displayed valuation as the cutoff, excluding subsequent fills.
    tickers = load("ticker_pnl", Filters(filters.account_id, filters.start, last.snapshot_date))
    if tickers:
        pnl = pd.DataFrame([{
            "Ticker": ticker.symbol,
            "Realizirani P&L": float(ticker.realized_pnl),
            "Nerealizirani P&L": float(ticker.unrealized_pnl),
        } for ticker in tickers]).set_index("Ticker")
        st.bar_chart(pnl, horizontal=True, stack=False, x_label=currency)
        st.caption(f"Realizirani P&L: izvršenja od {filters.start} do {last.snapshot_date}. "
                   "Nerealizirani P&L: otvorene pozicije na datum te valuacije, "
                   "uključujući ranije kupljene pozicije; nije promjena P&L-a u razdoblju.")
    else:
        st.info("Nema izvršenja ni spremljenih pozicija za prikaz P&L-a po tickeru.")
    prices = load("valuation_dates", filters)
    if prices:
        st.subheader("Datumi cijena pozicija")
        table(prices)
        if any(row["price_as_of"] < last.snapshot_date for row in prices):
            st.warning("Neke cijene prethode datumu valuacije.")


def paginated(method, filters):
    # Widget identity includes filters, so changing a filter resets the page.
    page = st.number_input("Stranica", min_value=1, step=1,
                           key=f"page:{method}:{filters}") - 1
    rows = load(method, filters, int(page))
    st.caption(f"25 zapisa po stranici · {'Postoji sljedeća stranica' if len(rows) > 25 else 'Zadnja stranica'}")
    return rows[:25]


def analyses(filters):
    rows = paginated("runs", filters)
    table(rows)
    if rows:
        run_id = st.selectbox("Detalji runa", [row["id"] for row in rows])
        table(load("decisions", filters.account_id, run_id))
        st.caption("Traženi ticker bez zapisa odluke nije potvrđeno obrađen; "
                   "pogledaj status i grešku runa.")


def reports(filters):
    rows = paginated("reports", filters)
    if not rows:
        st.info("Nema spremljenih izvještaja za odabrane filtre.")
        return
    by_id = {row["id"]: row for row in rows}
    selected = st.selectbox("Izvještaj", list(by_id), index=None,
                            placeholder="Odaberi izvještaj za učitavanje teksta",
                            format_func=lambda key: (
                                f"{by_id[key]['symbol']} · {by_id[key]['analysis_date']} · "
                                f"{by_id[key]['execution_key']} · {by_id[key]['report_type']}"))
    st.caption("Prikazuju se sve spremljene vrste izvještaja, uključujući complete_report.md.")
    if selected is not None:
        found = load("reports", filters, 0, 25, selected)
        if found:
            content = found[0]["content_markdown"]
            st.download_button("Preuzmi Markdown", content,
                               file_name=f"report-{selected}.md", mime="text/markdown")
            st.markdown(content, unsafe_allow_html=False)


def main():
    st.set_page_config(page_title="Trading Cockpit", page_icon="📊", layout="wide")
    st.title("Trading Cockpit")
    st.caption("Lokalni pregled · samo čitanje · simulirano paper trgovanje")
    if st.sidebar.button("Osvježi"):
        load.clear()
    try:
        accounts = load("accounts")
        names = {row["id"]: f"{row['name']} ({row['currency']})" for row in accounts}
        account_id = st.sidebar.selectbox("Račun", [None, *names],
                                          format_func=lambda key: names.get(key, "Single analysis"))
        start = st.sidebar.date_input("Od", date.today() - timedelta(days=90))
        end = st.sidebar.date_input("Do", date.today())
        if start > end:
            st.error("Početni datum mora biti prije završnog.")
            return
        pages = ["Izvještaji"] if account_id is None else ["Overview", "Analize", "Izvještaji"]
        page = st.sidebar.radio("Ekran", pages)
        ticker = st.sidebar.text_input("Ticker (točan simbol)", disabled=page == "Overview").strip()
        statuses = ["", "CREATED", "VALUATING", "ANALYZING", "PARTIAL_ANALYSIS", "PLANNED",
                    "EXECUTING", "SNAPSHOTTED", "COMPLETED", "FAILED", "CANCELLED"]
        status = st.sidebar.selectbox("Status runa", statuses,
                                      disabled=account_id is None or page == "Overview")
        filters = Filters(account_id, start.isoformat(), end.isoformat(), ticker, status)
        st.sidebar.caption("Cache: najviše 30 sekundi. Overview prikazuje cijeli račun.")
        st.subheader(page)
        if page == "Overview":
            currency = next(row["currency"] for row in accounts if row["id"] == account_id)
            overview(Filters(account_id, filters.start, filters.end), currency)
        elif page == "Analize":
            analyses(filters)
        else:
            reports(filters)
    except Exception:
        # Driver errors can contain host/user/SQL; keep them out of the browser.
        st.error("Podatke nije moguće učitati. Provjeri DB_* postavke, dostupnost MySQL-a "
                 "i postojeću shemu v4. Cockpit ne pokreće migracije.")


if __name__ == "__main__":
    main()
