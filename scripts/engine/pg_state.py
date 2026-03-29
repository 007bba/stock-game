"""
PostgreSQL-backed state store with real transaction semantics.

Replaces InMemoryState for production use.  On commit the current in-memory
state (accounts / positions / orders / trades / cash_ledger) is flushed to
Supabase.  On rollback everything is simply discarded – PostgreSQL handles
the atomicity.
"""

from __future__ import annotations

import copy
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor

from .state import (
    Account,
    CashLedgerEntry,
    Order,
    Position,
    Tick,
    Trade,
)


class PgState:
    """
    Drop-in replacement for InMemoryState that persists to PostgreSQL.

    All in-memory state is kept in Python dicts / lists (same as
    InMemoryState) so that matcher.py / ledger.py need no changes.
    After a tick completes successfully we flush everything to the DB via
    `flush()`.  On exception the transaction is rolled back and the in-memory
    state is restored from a deepcopy snapshot – the DB is never touched.
    """

    def __init__(self, database_url: str | None = None):
        if database_url is None:
            database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL not set")

        self._database_url = database_url
        self._conn = None  # live DB connection inside transaction
        self._tx_depth = 0  # nesting counter

        # ── in-memory state (same fields as InMemoryState) ────────────────
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

    # ── context manager ────────────────────────────────────────────────────────

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """
        PostgreSQL-backed transaction with re-entrant savepoint support.

        The outermost caller owns the real DB connection and COMMIT.
        Nested callers get a SAVEPOINT.

        On normal exit: outermost flushes + COMMITs; nested callers do nothing
        except release their savepoint.
        On exception: ALL savepoints down to outermost are rolled back, and
        the in-memory state is restored from the outermost snapshot.
        """
        outermost = self._tx_depth == 0
        self._tx_depth += 1

        snapshot = None
        if outermost:
            snapshot = copy.deepcopy({
                "accounts": self.accounts,
                "positions": self.positions,
                "orders": self.orders,
                "trades": self.trades,
                "cash_ledger": self.cash_ledger,
                "next_order_id": self.next_order_id,
                "next_trade_id": self.next_trade_id,
                "next_ledger_id": self.next_ledger_id,
                "sequence": self.sequence,
            })
            self._conn = psycopg2.connect(self._database_url)
            self._conn.autocommit = False

        savepoint_name = f"sp_{self._tx_depth}"
        cur = self._conn.cursor()
        cur.execute(f"SAVEPOINT {savepoint_name}")

        try:
            yield
            if outermost:
                self._flush()
                self._conn.commit()
        except Exception:
            cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            if outermost and snapshot is not None:
                self.accounts = snapshot["accounts"]
                self.positions = snapshot["positions"]
                self.orders = snapshot["orders"]
                self.trades = snapshot["trades"]
                self.cash_ledger = snapshot["cash_ledger"]
                self.next_order_id = snapshot["next_order_id"]
                self.next_trade_id = snapshot["next_trade_id"]
                self.next_ledger_id = snapshot["next_ledger_id"]
                self.sequence = snapshot["sequence"]
                self._conn.rollback()
            raise
        finally:
            cur.close()
            self._tx_depth -= 1
            if outermost:
                self._conn.close()
                self._conn = None

    # ── flush helpers ──────────────────────────────────────────────────────────

    def _flush(self):
        """Write current in-memory state to the DB inside the open transaction."""
        if self._conn is None:
            raise RuntimeError("_flush called outside a transaction")

        cur = self._conn.cursor()
        try:
            self._flush_accounts(cur)
            self._flush_positions(cur)
            self._flush_orders(cur)
            self._flush_trades(cur)
            self._flush_cash_ledger(cur)
            self._flush_sequences(cur)
        finally:
            cur.close()

    def _flush_accounts(self, cur):
        for acc in self.accounts.values():
            cur.execute(
                """
                INSERT INTO accounts
                  (id, season_id, user_id, initial_cash, available_cash,
                   frozen_cash, realized_pnl, updated_at)
                VALUES
                  (%(id)s, %(season_id)s, %(user_id)s, %(initial_cash)s,
                   %(available_cash)s, %(frozen_cash)s, %(realized_pnl)s, now())
                ON CONFLICT (id) DO UPDATE SET
                  available_cash = EXCLUDED.available_cash,
                  frozen_cash    = EXCLUDED.frozen_cash,
                  realized_pnl   = EXCLUDED.realized_pnl,
                  updated_at     = now()
                """,
                {
                    "id": acc.id,
                    "season_id": acc.season_id,
                    "user_id": str(acc.user_id),
                    "initial_cash": acc.initial_cash,
                    "available_cash": acc.available_cash,
                    "frozen_cash": acc.frozen_cash,
                    "realized_pnl": acc.realized_pnl,
                },
            )

    def _flush_positions(self, cur):
        for pos in self.positions.values():
            cur.execute(
                """
                INSERT INTO positions
                  (season_id, user_id, ts_code,
                   qty_total, qty_sellable, avg_cost, last_settled_game_day, updated_at)
                VALUES
                  (%(season_id)s, %(user_id)s, %(ts_code)s,
                   %(qty_total)s, %(qty_sellable)s, %(avg_cost)s,
                   %(last_settled_game_day)s, now())
                ON CONFLICT (season_id, user_id, ts_code) DO UPDATE SET
                  qty_total           = EXCLUDED.qty_total,
                  qty_sellable        = EXCLUDED.qty_sellable,
                  avg_cost            = EXCLUDED.avg_cost,
                  last_settled_game_day = EXCLUDED.last_settled_game_day,
                  updated_at          = now()
                """,
                {
                    "season_id": pos.season_id,
                    "user_id": str(pos.user_id),
                    "ts_code": pos.ts_code,
                    "qty_total": pos.qty_total,
                    "qty_sellable": pos.qty_sellable,
                    "avg_cost": pos.avg_cost,
                    "last_settled_game_day": pos.last_settled_game_day,
                },
            )

    def _flush_orders(self, cur):
        for order in self.orders.values():
            cur.execute(
                """
                INSERT INTO orders
                  (id, season_id, user_id, account_id, client_order_id,
                   ts_code, side, limit_price, quantity, remaining_qty,
                   status, phase_submitted, submitted_tick_id,
                                     effective_tick_id, reject_code, reject_reason, created_seq,
                                     created_at, updated_at)
                VALUES
                  (%(id)s, %(season_id)s, %(user_id)s, %(account_id)s,
                   %(client_order_id)s, %(ts_code)s, %(side)s, %(limit_price)s,
                   %(quantity)s, %(remaining_qty)s, %(status)s,
                   %(phase_submitted)s, %(submitted_tick_id)s,
                   %(effective_tick_id)s, %(reject_code)s, %(reject_reason)s,
                                     %(created_seq)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (id) DO UPDATE SET
                  remaining_qty  = EXCLUDED.remaining_qty,
                  status         = EXCLUDED.status,
                                    updated_at     = EXCLUDED.updated_at
                """,
                {
                    "id": order.id,
                    "season_id": order.season_id,
                    "user_id": str(order.user_id),
                    "account_id": order.account_id,
                    "client_order_id": order.client_order_id,
                    "ts_code": order.ts_code,
                    "side": order.side,
                    "limit_price": order.limit_price,
                    "quantity": order.quantity,
                    "remaining_qty": order.remaining_qty,
                    "status": order.status,
                    "phase_submitted": order.phase_submitted,
                    "submitted_tick_id": order.submitted_tick_id,
                    "effective_tick_id": order.effective_tick_id,
                    "reject_code": order.reject_code,
                    "reject_reason": order.reject_reason,
                    "created_seq": order.created_seq,
                    "created_at": order.created_at,
                    "updated_at": order.updated_at,
                },
            )

    def _flush_trades(self, cur):
        for trade in self.trades:
            cur.execute(
                """
                INSERT INTO trades
                  (id, season_id, tick_id, ts_code, trade_price, quantity,
                   buy_order_id, sell_order_id,
                   fee_buy, fee_sell, tax_sell, matched_at)
                VALUES
                  (%(id)s, %(season_id)s, %(tick_id)s, %(ts_code)s,
                   %(trade_price)s, %(quantity)s,
                   %(buy_order_id)s, %(sell_order_id)s,
                   %(fee_buy)s, %(fee_sell)s, %(tax_sell)s, %(matched_at)s)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    "id": trade.id,
                    "season_id": trade.season_id,
                    "tick_id": trade.tick_id,
                    "ts_code": trade.ts_code,
                    "trade_price": trade.trade_price,
                    "quantity": trade.quantity,
                    "buy_order_id": trade.buy_order_id,
                    "sell_order_id": trade.sell_order_id,
                    "fee_buy": trade.fee_buy,
                    "fee_sell": trade.fee_sell,
                    "tax_sell": trade.tax_sell,
                    "matched_at": trade.matched_at,
                },
            )

    def _flush_cash_ledger(self, cur):
        for entry in self.cash_ledger:
            cur.execute(
                """
                INSERT INTO cash_ledger
                  (id, season_id, user_id, account_id, entry_type,
                   amount, balance_after, ref_order_id, ref_trade_id, note)
                VALUES
                  (%(id)s, %(season_id)s, %(user_id)s, %(account_id)s,
                   %(entry_type)s, %(amount)s, %(balance_after)s,
                   %(ref_order_id)s, %(ref_trade_id)s, %(note)s)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    "id": entry.id,
                    "season_id": entry.season_id,
                    "user_id": str(entry.user_id),
                    "account_id": entry.account_id,
                    "entry_type": entry.entry_type,
                    "amount": entry.amount,
                    "balance_after": entry.balance_after,
                    "ref_order_id": entry.ref_order_id,
                    "ref_trade_id": entry.ref_trade_id,
                    "note": entry.note,
                },
            )

    def _flush_sequences(self, cur):
        """Sync next IDs to the DB so nextval() never repeats after restart."""
        for table, col, seq_name in [
            ("orders", "id", "orders_id_seq"),
            ("trades", "id", "trades_id_seq"),
            ("cash_ledger", "id", "cash_ledger_id_seq"),
        ]:
            max_id = self._max_id_for_table(cur, table, col)
            if max_id > 0:
                cur.execute(
                    "SELECT setval(%s, %s, true)",
                    (seq_name, max_id)
                )

    def _max_id_for_table(self, cur, table: str, col: str) -> int:
        """Return the global maximum id in a table, or 0 if empty."""
        cur.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
        return cur.fetchone()[0]

    # ── data load ─────────────────────────────────────────────────────────────

    def load_season_state(self, season_id: int):
        """
        Load all in-memory state for a given season from the DB.

        Call this once at the start of a simulation run to bootstrap
        accounts, positions, and any existing orders/trades.
        """
        conn = psycopg2.connect(self._database_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # accounts
                cur.execute(
                    "SELECT * FROM accounts WHERE season_id = %s",
                    (season_id,)
                )
                for row in cur.fetchall():
                    self.accounts[row["id"]] = Account(
                        id=row["id"],
                        season_id=row["season_id"],
                        user_id=row["user_id"],
                        initial_cash=float(row["initial_cash"]),
                        available_cash=float(row["available_cash"]),
                        frozen_cash=float(row["frozen_cash"]),
                        realized_pnl=float(row["realized_pnl"]),
                    )

                # positions
                cur.execute(
                    "SELECT * FROM positions WHERE season_id = %s",
                    (season_id,)
                )
                for row in cur.fetchall():
                    key = (row["season_id"], str(row["user_id"]), row["ts_code"])
                    self.positions[key] = Position(
                        season_id=row["season_id"],
                        user_id=row["user_id"],
                        ts_code=row["ts_code"],
                        qty_total=row["qty_total"],
                        qty_sellable=row["qty_sellable"],
                        avg_cost=float(row["avg_cost"]),
                        last_settled_game_day=row["last_settled_game_day"],
                    )

                # active orders
                cur.execute(
                    "SELECT * FROM orders WHERE season_id = %s "
                    "AND status IN ('active', 'partially_filled') "
                    "ORDER BY created_seq",
                    (season_id,)
                )
                for row in cur.fetchall():
                    self.orders[row["id"]] = Order(
                        id=row["id"],
                        season_id=row["season_id"],
                        user_id=row["user_id"],
                        account_id=row["account_id"],
                        client_order_id=row["client_order_id"],
                        ts_code=row["ts_code"],
                        side=row["side"],
                        limit_price=float(row["limit_price"]),
                        quantity=row["quantity"],
                        remaining_qty=row["remaining_qty"],
                        status=row["status"],
                        phase_submitted=row["phase_submitted"],
                        submitted_tick_id=row["submitted_tick_id"],
                        effective_tick_id=row["effective_tick_id"],
                        reject_code=row["reject_code"],
                        reject_reason=row["reject_reason"],
                        created_seq=row["created_seq"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )

                # sync next IDs (use GLOBAL max to avoid cross-season id collisions)
                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM orders")
                self.next_order_id = cur.fetchone()["next_id"]

                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM trades")
                self.next_trade_id = cur.fetchone()["next_id"]

                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM cash_ledger")
                self.next_ledger_id = cur.fetchone()["next_id"]

                cur.execute(
                    "SELECT COALESCE(MAX(created_seq), 0) + 1 AS next_seq FROM orders WHERE season_id = %s",
                    (season_id,)
                )
                self.sequence = cur.fetchone()["next_seq"]
        finally:
            conn.close()

    # ── same interface as InMemoryState ──────────────────────────────────────

    def get_position(
        self, season_id: int, user_id: str, ts_code: str
    ) -> Position:
        key = (season_id, user_id, ts_code)
        if key not in self.positions:
            self.positions[key] = Position(
                season_id=season_id,
                user_id=user_id,
                ts_code=ts_code,
            )
        return self.positions[key]

    def append_error(self, message: str):
        self.error_log.append(message)

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
