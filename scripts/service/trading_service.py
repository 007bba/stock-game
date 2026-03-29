from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from scripts.engine.orchestrator import EngineOrchestrator, PlaceOrderRequest
from scripts.engine.state import Account, Order, Quote, Tick

if TYPE_CHECKING:
    from scripts.engine.state import Trade
    from scripts.service.event_publisher import EventPublisher


class TradingService:
    def __init__(self, state, season_id: int | None = None, event_publisher: "EventPublisher | None" = None):
        self.state = state
        self.event_publisher = event_publisher
        if hasattr(state, "load_season_state") and season_id is not None:
            state.load_season_state(season_id)
        self.orchestrator = EngineOrchestrator(state=state, season_id=season_id)

    def set_event_publisher(self, event_publisher: "EventPublisher | None"):
        self.event_publisher = event_publisher

    def place_order(self, tick: Tick, quote: Quote, req: PlaceOrderRequest) -> dict:
        order = self.orchestrator.place_order(tick=tick, quote=quote, req=req)
        return self._order_to_dto(order)

    def process_tick(self, tick: Tick, quotes_by_code: dict[str, Quote]) -> dict:
        trade_ids = self.orchestrator.process_tick(tick=tick, quotes_by_code=quotes_by_code)

        if self.event_publisher is not None:
            self._publish_tick_events(tick=tick, trade_ids=trade_ids)

        return {
            "tickId": tick.id,
            "tradeIds": trade_ids,
            "tradeCount": len(trade_ids),
        }

    def _publish_tick_events(self, tick: Tick, trade_ids: list[int]):
        if self.event_publisher is None:
            return

        self.event_publisher.publish_to_season(
            season_id=tick.season_id,
            event="tick_update",
            payload={
                "seasonId": tick.season_id,
                "tickId": tick.id,
                "gameDayNo": tick.game_day_no,
                "minuteOfDay": tick.minute_of_day,
                "phase": tick.phase,
                "matchingMode": tick.matching_mode,
                "tradeCount": len(trade_ids),
            },
        )

        if not trade_ids:
            return

        trade_id_set = set(trade_ids)
        trades_by_id = {trade.id: trade for trade in self.state.trades if trade.id in trade_id_set}
        impacted_users: set[str] = set()
        impacted_positions: set[tuple[str, str]] = set()

        for trade_id in trade_ids:
            trade = trades_by_id.get(trade_id)
            if trade is None:
                continue

            self.event_publisher.publish_to_season(
                season_id=tick.season_id,
                event="trade_matched",
                payload=self._trade_to_dto(trade),
            )

            buy_order = self.state.orders.get(trade.buy_order_id)
            sell_order = self.state.orders.get(trade.sell_order_id)

            if buy_order is not None:
                impacted_users.add(str(buy_order.user_id))
                impacted_positions.add((str(buy_order.user_id), trade.ts_code))
                self.event_publisher.publish_to_user(
                    user_id=str(buy_order.user_id),
                    season_id=tick.season_id,
                    event="order_matched",
                    payload={
                        "seasonId": tick.season_id,
                        "order": self._order_to_dto(buy_order),
                        "trade": self._trade_to_dto(trade),
                        "role": "buy",
                    },
                )

            if sell_order is not None:
                impacted_users.add(str(sell_order.user_id))
                impacted_positions.add((str(sell_order.user_id), trade.ts_code))
                self.event_publisher.publish_to_user(
                    user_id=str(sell_order.user_id),
                    season_id=tick.season_id,
                    event="order_matched",
                    payload={
                        "seasonId": tick.season_id,
                        "order": self._order_to_dto(sell_order),
                        "trade": self._trade_to_dto(trade),
                        "role": "sell",
                    },
                )

        for user_id, ts_code in impacted_positions:
            position = self.state.get_position(tick.season_id, user_id, ts_code)
            self.event_publisher.publish_to_user(
                user_id=user_id,
                season_id=tick.season_id,
                event="position_update",
                payload={
                    "seasonId": tick.season_id,
                    "userId": user_id,
                    "tsCode": ts_code,
                    "qtyTotal": position.qty_total,
                    "qtySellable": position.qty_sellable,
                    "avgCost": position.avg_cost,
                },
            )

        for user_id in impacted_users:
            account = self._find_account_in_state(season_id=tick.season_id, user_id=user_id)
            if account is None:
                continue
            self.event_publisher.publish_to_user(
                user_id=user_id,
                season_id=tick.season_id,
                event="account_update",
                payload={
                    "seasonId": tick.season_id,
                    "userId": user_id,
                    "accountId": account.id,
                    "availableCash": account.available_cash,
                    "frozenCash": account.frozen_cash,
                    "realizedPnl": account.realized_pnl,
                },
            )

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

    def _trade_to_dto(self, trade: "Trade") -> dict:
        return {
            "tradeId": trade.id,
            "seasonId": trade.season_id,
            "tickId": trade.tick_id,
            "tsCode": trade.ts_code,
            "price": trade.trade_price,
            "qty": trade.quantity,
            "buyOrderId": trade.buy_order_id,
            "sellOrderId": trade.sell_order_id,
            "feeBuy": trade.fee_buy,
            "feeSell": trade.fee_sell,
            "taxSell": trade.tax_sell,
            "matchedAt": trade.matched_at.isoformat() if trade.matched_at else None,
        }
