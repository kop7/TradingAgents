"""Management and reporting commands for persistent paper accounts."""

from __future__ import annotations

import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.paper import PaperRepository
from tradingagents.paper.exports import export_account
from tradingagents.paper.money import micros_to_money, nanos_to_quantity
from tradingagents.paper.statistics import portfolio_summary

paper_app = typer.Typer(help="Persistent virtual accounts, positions, statistics, and exports.")
console = Console()
_OUTPUT_OPTION = typer.Option(None, "--output")


def repository() -> PaperRepository:
    return PaperRepository(DEFAULT_CONFIG["paper_db_path"])


def resolve_account(repo: PaperRepository, name: str):
    try:
        return repo.get_account(name)
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@paper_app.command("account-create")
def account_create(
    name: str = typer.Option("default", "--name", help="Unique paper account name."),
    cash: float = typer.Option(1000.0, "--cash", min=0.01, help="Initial virtual cash."),
    currency: str = typer.Option("USD", "--currency"),
    benchmark: str = typer.Option("URA", "--benchmark"),
):
    repo = repository()
    existed = True
    try:
        account = repo.get_account(name)
    except LookupError:
        existed = False
        account = repo.create_account(
            name,
            cash,
            currency=currency,
            benchmark_symbol=benchmark,
            strategy_config={
                "buy_notional": DEFAULT_CONFIG["paper_buy_notional"],
                "overweight_notional": DEFAULT_CONFIG["paper_overweight_notional"],
                "max_position_pct": DEFAULT_CONFIG["paper_max_position_pct"],
                "cash_reserve_pct": DEFAULT_CONFIG["paper_cash_reserve_pct"],
                "slippage_bps": DEFAULT_CONFIG["paper_slippage_bps"],
            },
        )
    verb = "already exists" if existed else "created"
    console.print(
        f"[green]Paper account {verb}:[/green] {account.name} — "
        f"cash {repo.get_balance(account.id):,.2f} {account.currency}"
    )


@paper_app.command("account-list")
def account_list():
    repo = repository()
    table = Table(title="Paper accounts", box=box.SIMPLE_HEAVY)
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Cash", justify="right")
    table.add_column("Currency")
    table.add_column("Benchmark")
    table.add_column("Status")
    for account in repo.list_accounts():
        table.add_row(
            str(account.id), account.name, f"{repo.get_balance(account.id):,.2f}",
            account.currency, account.benchmark_symbol or "—", account.status,
        )
    console.print(table)


@paper_app.command("account-show")
def account_show(name: str = typer.Option("default", "--account")):
    repo = repository()
    account = resolve_account(repo, name)
    positions = repo.get_positions(account.id)
    latest = repo.latest_snapshot(account.id)
    console.print(f"[bold cyan]{account.name}[/bold cyan] (ID {account.id})")
    console.print(f"Cash: {repo.get_balance(account.id):,.2f} {account.currency}")
    console.print(f"Benchmark: {account.benchmark_symbol or '—'}")
    console.print(f"Strategy: {account.strategy_version or '—'}")
    if latest:
        console.print(
            f"Latest equity ({latest['snapshot_date']}): "
            f"{micros_to_money(latest['total_equity_micros']):,.2f} {account.currency}"
        )
    table = Table(title="Open positions", box=box.SIMPLE_HEAVY)
    table.add_column("Ticker")
    table.add_column("Quantity", justify="right")
    table.add_column("Average", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("Value", justify="right")
    for position in positions:
        quantity = nanos_to_quantity(position.quantity_nanos)
        price = micros_to_money(position.last_price_micros)
        table.add_row(
            position.symbol, f"{quantity:.6f}",
            f"{micros_to_money(position.average_cost_micros):,.4f}",
            f"{price:,.4f}", f"{quantity * price:,.2f}",
        )
    console.print(table)


@paper_app.command("trades")
def trades(
    name: str = typer.Option("default", "--account"),
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
):
    repo = repository()
    account = resolve_account(repo, name)
    clauses = ["f.account_id = ?"]
    parameters: list[object] = [account.id]
    if start:
        clauses.append("date(f.executed_at) >= date(?)")
        parameters.append(start)
    if end:
        clauses.append("date(f.executed_at) <= date(?)")
        parameters.append(end)
    with repo.connect() as connection:
        rows = connection.execute(
            """SELECT f.executed_at, f.symbol, d.rating, f.side,
                      f.quantity_nanos, f.effective_price_micros,
                      f.gross_notional_micros, f.realized_pnl_micros
               FROM fills f
               JOIN orders o ON o.id = f.order_id
               JOIN decisions d ON d.id = o.decision_id
               WHERE """ + " AND ".join(clauses) + " ORDER BY f.executed_at, f.id",
            parameters,
        ).fetchall()
    table = Table(title=f"Trades — {account.name}", box=box.SIMPLE_HEAVY)
    for label in ("Executed", "Ticker", "Rating", "Side", "Quantity", "Price", "Notional", "Realized P&L"):
        table.add_column(label, justify="right" if label in {"Quantity", "Price", "Notional", "Realized P&L"} else "left")
    for row in rows:
        table.add_row(
            row["executed_at"], row["symbol"], row["rating"], row["side"],
            f"{nanos_to_quantity(row['quantity_nanos']):.6f}",
            f"{micros_to_money(row['effective_price_micros']):,.4f}",
            f"{micros_to_money(row['gross_notional_micros']):,.2f}",
            f"{micros_to_money(row['realized_pnl_micros']):,.2f}",
        )
    console.print(table)


@paper_app.command("stats")
def stats(
    name: str = typer.Option("default", "--account"),
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
):
    repo = repository()
    account = resolve_account(repo, name)
    with repo.connect() as connection:
        summary = portfolio_summary(connection, str(account.id), start_date=start, end_date=end)
    console.print(f"[bold cyan]Paper statistics — {account.name}[/bold cyan]")
    console.print(f"Period: {summary.start_date or '—'} → {summary.end_date or '—'}")
    console.print(f"Cash: {summary.end_cash:,.2f} {account.currency}")
    console.print(f"Positions value: {summary.end_market_value:,.2f} {account.currency}")
    console.print(f"Total equity: {summary.end_equity:,.2f} {account.currency}")
    console.print(f"Total P&L: {summary.total_pnl:,.2f} {account.currency}")
    console.print(f"Return: {summary.portfolio_return:.2%}")
    console.print(f"Max drawdown: {summary.max_drawdown:.2%}")
    if summary.benchmark_return is not None:
        console.print(f"Benchmark return: {summary.benchmark_return:.2%}")
        console.print(f"Alpha: {summary.alpha:.2%}")
    table = Table(title="By ticker", box=box.SIMPLE_HEAVY)
    for label in ("Ticker", "Bought", "Sold", "Current value", "Realized", "Unrealized", "Total P&L"):
        table.add_column(label, justify="right" if label != "Ticker" else "left")
    for ticker in summary.tickers:
        table.add_row(
            ticker.symbol, f"{ticker.bought:,.2f}", f"{ticker.sold:,.2f}",
            f"{ticker.current_value:,.2f}", f"{ticker.realized_pnl:,.2f}",
            f"{ticker.unrealized_pnl:,.2f}", f"{ticker.total_pnl:,.2f}",
        )
    console.print(table)


@paper_app.command("export")
def export(
    name: str = typer.Option("default", "--account"),
    output: Path | None = _OUTPUT_OPTION,
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
):
    repo = repository()
    account = resolve_account(repo, name)
    target = output or (
        Path.cwd() / "exports" /
        f"{account.name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    with repo.connect() as connection:
        exported = export_account(
            connection, account.id, target, start_date=start, end_date=end
        )
    console.print(f"[green]Export saved to:[/green] {exported.resolve()}")


__all__ = ["paper_app"]
