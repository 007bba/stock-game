from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterator, List
import copy


@dataclass
class Tick:
    id: int
    season_id: int
    game_day_no: int
    minute_of_day: int
    phase: str
    matching_mode: str
    is_tradable: bool
    is_matching_point: bool


@dataclass
class Quote:
    ts_code: str
    ref_price: float
    upper_limit_price: float
    lower_limit_price: float
    is_halted: bool


@dataclass
class Account:
    id: int
    season_id: int
    user_id: str
    initial_cash: float
    available_cash: float
    frozen_cash: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class Position:
    season_id: int
    user_id: str
    ts_code: str
    qty_total: int = 0
    qty_sellable: int = 0
    avg_cost: float = 0.0
    last_settled_game_day: int = 0


@dataclass
class Order:
    id: int
    season_id: int
    user_id: str
    account_id: int
    client_order_id: str
    ts_code: str
    side: str
    limit_price: float
    quantity: int
    remaining_qty: int
    status: str
    phase_submitted: str
    submitted_tick_id: int
    effective_tick_id: int | None = None
    reject_code: str | None = None
    reject_reason: str | None = None
    created_seq: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Trade:
    id: int
    season_id: int
    tick_id: int
    ts_code: str
    trade_price: float
    quantity: int
    buy_order_id: int
    sell_order_id: int
    fee_buy: float
    fee_sell: float
    tax_sell: float
    matched_at: datetime


@dataclass
class CashLedgerEntry:
    id: int
    season_id: int
    user_id: str
    account_id: int
    entry_type: str
    amount: float
    balance_after: float
    ref_order_id: int | None = None
    ref_trade_id: int | None = None
    note: str | None = None


class InMemoryState:
    """MVP state store with transaction rollback semantics."""

    def __init__(self):
        self.accounts: Dict[int, Account] = {}
        self.positions: Dict[tuple[int, str, str], Position] = {}
        self.orders: Dict[int, Order] = {}
        self.trades: List[Trade] = []
        self.cash_ledger: List[CashLedgerEntry] = []
        self.next_order_id: int = 1
        self.next_trade_id: int = 1
        self.next_ledger_id: int = 1
        self.sequence: int = 1
        self.error_log: List[str] = []

    def get_position(self, season_id: int, user_id: str, ts_code: str) -> Position:
        key = (season_id, user_id, ts_code)
        if key not in self.positions:
            self.positions[key] = Position(season_id=season_id, user_id=user_id, ts_code=ts_code)
        return self.positions[key]

    def append_error(self, message: str):
        self.error_log.append(message)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        snapshot = copy.deepcopy(
            {
                "accounts": self.accounts,
                "positions": self.positions,
                "orders": self.orders,
                "trades": self.trades,
                "cash_ledger": self.cash_ledger,
                "next_order_id": self.next_order_id,
                "next_trade_id": self.next_trade_id,
                "next_ledger_id": self.next_ledger_id,
                "sequence": self.sequence,
            }
        )
        try:
            yield
        except Exception:
            self.accounts = snapshot["accounts"]
            self.positions = snapshot["positions"]
            self.orders = snapshot["orders"]
            self.trades = snapshot["trades"]
            self.cash_ledger = snapshot["cash_ledger"]
            self.next_order_id = snapshot["next_order_id"]
            self.next_trade_id = snapshot["next_trade_id"]
            self.next_ledger_id = snapshot["next_ledger_id"]
            self.sequence = snapshot["sequence"]
            raise

    def create_order_id(self) -> int:
        value = self.next_order_id
        self.next_order_id += 1
        return value

    def create_trade_id(self) -> int:
        value = self.next_trade_id
        self.next_trade_id += 1
        return value

    def create_ledger_id(self) -> int:
        value = self.next_ledger_id
        self.next_ledger_id += 1
        return value

    def create_sequence(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
