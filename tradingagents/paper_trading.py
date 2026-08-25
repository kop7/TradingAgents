"""Local, long-only paper-trading account for TradingAgents decisions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.symbol_utils import normalize_symbol


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    average_price: float
    last_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.last_price - self.average_price)


@dataclass(frozen=True)
class PortfolioSnapshot:
    initial_cash: float
    cash: float
    positions: tuple[Position, ...]
    realized_pnl: float

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def total_equity(self) -> float:
        return self.cash + self.market_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions)

    @property
    def total_return(self) -> float:
        return (
            (self.total_equity - self.initial_cash) / self.initial_cash
            if self.initial_cash
            else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "market_value": self.market_value,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_return": self.total_return,
            "positions": [
                {
                    **asdict(position),
                    "market_value": position.market_value,
                    "unrealized_pnl": position.unrealized_pnl,
                }
                for position in self.positions
            ],
        }


@dataclass(frozen=True)
class TradeResult:
    symbol: str
    trade_date: str
    decision: str
    side: str
    quantity: float
    price: float
    cash_after: float
    message: str
    duplicate: bool = False


def fetch_execution_price(symbol: str, trade_date: str) -> float:
    """Return the latest verified close at or before ``trade_date``."""
    # Keep the persistence/account layer usable without importing the heavier
    # pandas/yfinance stack until a live price is actually requested.
    from tradingagents.dataflows.stockstats_utils import load_ohlcv

    data = load_ohlcv(symbol, trade_date)
    if data.empty or "Close" not in data.columns:
        raise ValueError(f"No closing price available for {symbol} on {trade_date}")
    price = float(data.iloc[-1]["Close"])
    if price <= 0:
        raise ValueError(f"Invalid closing price for {symbol}: {price}")
    return price


class PaperPortfolio:
    """Persistent virtual account backed by a local SQLite database."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        initial_cash: float = 1_000.0,
        max_position_pct: float = 0.20,
    ):
        if initial_cash <= 0:
            raise ValueError("initial_cash must be greater than zero")
        if not 0 < max_position_pct <= 1:
            raise ValueError("max_position_pct must be between 0 and 1")
        self.db_path = Path(db_path).expanduser()
        self.initial_cash = float(initial_cash)
        self.max_position_pct = float(max_position_pct)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_cash REAL NOT NULL,
                    cash REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    average_price REAL NOT NULL,
                    last_price REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    cash_after REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    UNIQUE(symbol, trade_date)
                );
                """
            )
            connection.execute(
                """INSERT OR IGNORE INTO account (id, initial_cash, cash, created_at)
                VALUES (1, ?, ?, ?)""",
                (self.initial_cash, self.initial_cash, self._now()),
            )

    def snapshot(self) -> PortfolioSnapshot:
        with self._connect() as connection:
            return self._snapshot(connection)

    def _snapshot(self, connection: sqlite3.Connection) -> PortfolioSnapshot:
        account = connection.execute(
            "SELECT initial_cash, cash FROM account WHERE id = 1"
        ).fetchone()
        rows = connection.execute(
            """SELECT symbol, quantity, average_price, last_price FROM positions
            WHERE quantity > 0 ORDER BY symbol"""
        ).fetchall()
        realized = connection.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades"
        ).fetchone()[0]
        return PortfolioSnapshot(
            initial_cash=float(account["initial_cash"]),
            cash=float(account["cash"]),
            positions=tuple(
                Position(
                    symbol=row["symbol"],
                    quantity=float(row["quantity"]),
                    average_price=float(row["average_price"]),
                    last_price=float(row["last_price"]),
                )
                for row in rows
            ),
            realized_pnl=float(realized),
        )

    def apply_decision(
        self,
        *,
        symbol: str,
        trade_date: str,
        decision_text: str,
        price: float,
    ) -> TradeResult:
        """Apply one Portfolio Manager decision at a supplied virtual fill price."""
        if price <= 0:
            raise ValueError("price must be greater than zero")
        canonical = normalize_symbol(symbol)
        decision = parse_rating(decision_text)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT side, quantity, price, cash_after, decision FROM trades
                WHERE symbol = ? AND trade_date = ?""",
                (canonical, trade_date),
            ).fetchone()
            if existing:
                return TradeResult(
                    canonical,
                    trade_date,
                    existing["decision"],
                    existing["side"],
                    float(existing["quantity"]),
                    float(existing["price"]),
                    float(existing["cash_after"]),
                    "Decision for this symbol and date was already processed.",
                    True,
                )

            cash = float(
                connection.execute("SELECT cash FROM account WHERE id = 1").fetchone()[0]
            )
            row = connection.execute(
                """SELECT quantity, average_price FROM positions
                WHERE symbol = ?""",
                (canonical,),
            ).fetchone()
            quantity = float(row["quantity"]) if row else 0.0
            average_price = float(row["average_price"]) if row else 0.0
            if row:
                connection.execute(
                    "UPDATE positions SET last_price = ?, updated_at = ? WHERE symbol = ?",
                    (price, self._now(), canonical),
                )
            equity = self._snapshot(connection).total_equity

            side = "HOLD"
            trade_quantity = 0.0
            realized_pnl = 0.0
            message = "No virtual trade was required."

            if decision in {"Buy", "Overweight"}:
                capacity = max(0.0, equity * self.max_position_pct - quantity * price)
                requested = capacity
                if decision == "Overweight":
                    requested = min(capacity, equity * 0.10)
                spend = min(cash, requested)
                trade_quantity = spend / price if spend > 0 else 0.0
                if trade_quantity > 0:
                    side = "BUY"
                    new_quantity = quantity + trade_quantity
                    new_average = (
                        quantity * average_price + trade_quantity * price
                    ) / new_quantity
                    cash -= spend
                    connection.execute(
                        """INSERT INTO positions
                        (symbol, quantity, average_price, last_price, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET
                            quantity = excluded.quantity,
                            average_price = excluded.average_price,
                            last_price = excluded.last_price,
                            updated_at = excluded.updated_at""",
                        (canonical, new_quantity, new_average, price, self._now()),
                    )
                    message = f"Virtually bought {trade_quantity:.6f} {canonical}."
                else:
                    message = "Position is already at its limit or no cash is available."
            elif decision in {"Underweight", "Sell"} and quantity > 0:
                trade_quantity = quantity if decision == "Sell" else quantity / 2
                cash += trade_quantity * price
                realized_pnl = trade_quantity * (price - average_price)
                remaining = quantity - trade_quantity
                side = "SELL"
                if remaining <= 1e-12:
                    connection.execute("DELETE FROM positions WHERE symbol = ?", (canonical,))
                else:
                    connection.execute(
                        """UPDATE positions SET quantity = ?, last_price = ?, updated_at = ?
                        WHERE symbol = ?""",
                        (remaining, price, self._now(), canonical),
                    )
                message = f"Virtually sold {trade_quantity:.6f} {canonical}."
            elif decision in {"Underweight", "Sell"}:
                message = "There is no open position to sell."

            connection.execute("UPDATE account SET cash = ? WHERE id = 1", (cash,))
            connection.execute(
                """INSERT INTO trades
                (symbol, trade_date, executed_at, decision, side, quantity, price,
                 cash_after, realized_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    canonical,
                    trade_date,
                    self._now(),
                    decision,
                    side,
                    trade_quantity,
                    price,
                    cash,
                    realized_pnl,
                ),
            )

        return TradeResult(
            canonical,
            trade_date,
            decision,
            side,
            trade_quantity,
            price,
            cash,
            message,
        )

    def write_snapshot(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.snapshot().to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output
