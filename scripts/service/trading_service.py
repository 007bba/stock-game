from __future__ import annotations

from dataclasses import asdict
from typing import Any

from scripts.engine.orchestrator import EngineOrchestrator, PlaceOrderRequest
from scripts.engine.state import Account, Order, Quote, Tick


class TradingService:
    def __init__(self, state, season_id: int | None = None):
        self.state = state
        if hasattr(state, "load_season_state") and season_id is not None:
            state.load_season_state(season_id)
        self.orchestrator = EngineOrchestrator(state=state, season_id=season_id)

    def place_order(self, tick: Tick, quote: Quote, req: PlaceOrderRequest) -> dict:
        order = self.orchestrator.place_order(tick=tick, quote=quote, req=req)
        return self._order_to_dto(order)

    def process_tick(self, tick: Tick, quotes_by_code: dict[str, Quote]) -> dict:
        trade_ids = self.orchestrator.process_tick(tick=tick, quotes_by_code=quotes_by_code)
        return {
            "tickId": tick.id,
            "tradeIds": trade_ids,
            "tradeCount": len(trade_ids),
        }

    def list_orders(self, season_id: int, user_id: str, status: str | None = None, ts_code: str | None = None) -> list[dict]:
        result: list[dict] = []
        for order in self.state.orders.values():
            if order.season_id != season_id or order.user_id != user_id:
                continue
            if status and order.status != status:
                continue
            if ts_code and order.ts_code != ts_code:
                continue
            result.append(self._order_to_dto(order))
        result.sort(key=lambda item: item["id"])
        return result

    def join_season(self, season_id: int, user_id: str, initial_cash: float = 1_000_000.0) -> dict:
        existing = self._find_account_in_state(season_id=season_id, user_id=user_id)
        if existing is not None:
            return self._account_to_join_dto(existing, is_new_join=False)

        account: Account | None = None
        is_new_join = False

        with self.state.transaction():
            account = self._find_account_in_state(season_id=season_id, user_id=user_id)
            if account is None:
                account = self._find_account_in_db(season_id=season_id, user_id=user_id)

            if account is None:
                if not self._season_exists_in_db(season_id=season_id):
                    raise ValueError("SEASON_NOT_FOUND")

                account_id = self._allocate_account_id()
                account = Account(
                    id=account_id,
                    season_id=season_id,
                    user_id=user_id,
                    initial_cash=initial_cash,
                    available_cash=initial_cash,
                    frozen_cash=0.0,
                    realized_pnl=0.0,
                )
                is_new_join = True

            self.state.accounts[account.id] = account

        if account is None:
            raise RuntimeError("join season failed to resolve account")

        return self._account_to_join_dto(account, is_new_join=is_new_join)

    def _find_account_in_state(self, season_id: int, user_id: str) -> Account | None:
        for account in self.state.accounts.values():
            if account.season_id == season_id and str(account.user_id) == user_id:
                return account
        return None

    def _get_state_db_conn(self) -> Any | None:
        return getattr(self.state, "_conn", None)

    def _find_account_in_db(self, season_id: int, user_id: str) -> Account | None:
        conn = self._get_state_db_conn()
        if conn is None:
            return None

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, season_id, user_id, initial_cash, available_cash, frozen_cash, realized_pnl
                FROM accounts
                WHERE season_id = %s AND user_id = %s
                LIMIT 1
                """,
                (season_id, user_id),
            )
            row = cur.fetchone()

        if row is None:
            return None

        return Account(
            id=int(row[0]),
            season_id=int(row[1]),
            user_id=str(row[2]),
            initial_cash=float(row[3]),
            available_cash=float(row[4]),
            frozen_cash=float(row[5]),
            realized_pnl=float(row[6]),
        )

    def _season_exists_in_db(self, season_id: int) -> bool:
        conn = self._get_state_db_conn()
        if conn is None:
            return True

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM seasons WHERE id = %s LIMIT 1", (season_id,))
            return cur.fetchone() is not None

    def _allocate_account_id(self) -> int:
        conn = self._get_state_db_conn()
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute("SELECT nextval('accounts_id_seq')")
                value = cur.fetchone()
            if value is None:
                raise RuntimeError("failed to allocate account id")
            return int(value[0])

        return max(self.state.accounts.keys(), default=0) + 1

    def _account_to_join_dto(self, account: Account, *, is_new_join: bool) -> dict:
        return {
            "seasonId": account.season_id,
            "accountId": account.id,
            "isNewJoin": is_new_join,
            "initialCash": account.initial_cash,
            "availableCash": account.available_cash,
            "frozenCash": account.frozen_cash,
            "realizedPnl": account.realized_pnl,
        }

    def _order_to_dto(self, order: Order) -> dict:
        raw = asdict(order)
        return {
            "id": raw["id"],
            "clientOrderId": raw["client_order_id"],
            "tsCode": raw["ts_code"],
            "side": raw["side"],
            "limitPrice": raw["limit_price"],
            "quantity": raw["quantity"],
            "remainingQty": raw["remaining_qty"],
            "status": raw["status"],
            "rejectCode": raw["reject_code"],
            "rejectReason": raw["reject_reason"],
            "createdAt": raw["created_at"].isoformat() if raw.get("created_at") else None,
            "updatedAt": raw["updated_at"].isoformat() if raw.get("updated_at") else None,
        }
