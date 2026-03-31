from __future__ import annotations

from contextlib import contextmanager
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
                "isTradable": tick.is_tradable,
                "isMatchingPoint": tick.is_matching_point,
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
        db_orders = self._list_orders_from_db(season_id=season_id, user_id=user_id, status=status, ts_code=ts_code)
        if db_orders is not None:
            return db_orders

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

    def get_account_snapshot(self, season_id: int, user_id: str) -> dict | None:
        snapshot = self._get_account_snapshot_from_db(season_id=season_id, user_id=user_id)
        if snapshot is not None:
            return snapshot

        account = self._find_account_in_state(season_id=season_id, user_id=user_id)
        if account is None:
            return None

        positions = [
            {
                "tsCode": position.ts_code,
                "qty": position.qty_total,
                "avgPrice": position.avg_cost,
            }
            for (position_season_id, position_user_id, _), position in self.state.positions.items()
            if position_season_id == season_id and str(position_user_id) == user_id and position.qty_total > 0
        ]
        positions.sort(key=lambda item: item["tsCode"])

        return {
            "seasonId": account.season_id,
            "accountId": account.id,
            "initialCash": account.initial_cash,
            "availableCash": account.available_cash,
            "frozenCash": account.frozen_cash,
            "realizedPnl": account.realized_pnl,
            "positions": positions,
        }

    def join_season(
        self,
        season_id: int,
        user_id: str,
        initial_cash: float = 1_000_000.0,
        email: str | None = None,
    ) -> dict:
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

                self._ensure_user_exists(user_id=user_id, email=email)
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

    def _list_orders_from_db(
        self,
        season_id: int,
        user_id: str,
        status: str | None = None,
        ts_code: str | None = None,
    ) -> list[dict] | None:
        query = [
            """
            SELECT
              id,
              client_order_id,
              ts_code,
              side,
              limit_price,
              quantity,
              remaining_qty,
              status,
              reject_code,
              reject_reason,
              created_at,
              updated_at
            FROM orders
            WHERE season_id = %s
              AND user_id = %s
            """
        ]
        params: list[Any] = [season_id, user_id]

        if status:
            query.append("AND status = %s")
            params.append(status)
        if ts_code:
            query.append("AND ts_code = %s")
            params.append(ts_code)

        query.append("ORDER BY id ASC")

        with self._db_cursor() as cur:
            if cur is None:
                return None
            cur.execute("\n".join(query), tuple(params))
            rows = cur.fetchall()

        return [
            {
                "id": int(row[0]),
                "clientOrderId": str(row[1]),
                "tsCode": str(row[2]),
                "side": str(row[3]),
                "limitPrice": float(row[4]),
                "quantity": int(row[5]),
                "remainingQty": int(row[6]),
                "status": str(row[7]),
                "rejectCode": row[8],
                "rejectReason": row[9],
                "createdAt": row[10].isoformat() if row[10] else None,
                "updatedAt": row[11].isoformat() if row[11] else None,
            }
            for row in rows
        ]

    def _get_account_snapshot_from_db(self, season_id: int, user_id: str) -> dict | None:
        with self._db_cursor() as cur:
            if cur is None:
                return None
            cur.execute(
                """
                SELECT id, season_id, initial_cash, available_cash, frozen_cash, realized_pnl
                FROM accounts
                WHERE season_id = %s AND user_id = %s
                LIMIT 1
                """,
                (season_id, user_id),
            )
            account_row = cur.fetchone()

            if account_row is None:
                return None

            cur.execute(
                """
                SELECT ts_code, qty_total, avg_cost
                FROM positions
                WHERE season_id = %s
                  AND user_id = %s
                  AND qty_total > 0
                ORDER BY ts_code
                """,
                (season_id, user_id),
            )
            position_rows = cur.fetchall()

        return {
            "seasonId": int(account_row[1]),
            "accountId": int(account_row[0]),
            "initialCash": float(account_row[2]),
            "availableCash": float(account_row[3]),
            "frozenCash": float(account_row[4]),
            "realizedPnl": float(account_row[5]),
            "positions": [
                {
                    "tsCode": str(row[0]),
                    "qty": int(row[1]),
                    "avgPrice": float(row[2]),
                }
                for row in position_rows
            ],
        }

    def _find_account_in_state(self, season_id: int, user_id: str) -> Account | None:
        for account in self.state.accounts.values():
            if account.season_id == season_id and str(account.user_id) == user_id:
                return account
        return None

    def _get_state_db_conn(self) -> Any | None:
        return getattr(self.state, "_conn", None)

    @contextmanager
    def _db_cursor(self):
        conn = self._get_state_db_conn()
        if conn is not None:
            with conn.cursor() as cur:
                yield cur
            return

        database_url = getattr(self.state, "_database_url", None)
        if not database_url:
            yield None
            return

        import psycopg2

        temp_conn = psycopg2.connect(database_url)
        try:
            with temp_conn.cursor() as cur:
                yield cur
        finally:
            temp_conn.close()

    def _find_account_in_db(self, season_id: int, user_id: str) -> Account | None:
        with self._db_cursor() as cur:
            if cur is None:
                return None

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
        with self._db_cursor() as cur:
            if cur is None:
                return True

            cur.execute("SELECT 1 FROM seasons WHERE id = %s LIMIT 1", (season_id,))
            return cur.fetchone() is not None

    def _allocate_account_id(self) -> int:
        with self._db_cursor() as cur:
            if cur is None:
                return max(self.state.accounts.keys(), default=0) + 1

            cur.execute("SELECT nextval('accounts_id_seq')")
            value = cur.fetchone()
            if value is None:
                raise RuntimeError("failed to allocate account id")
            return int(value[0])

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

    def _ensure_user_exists(self, user_id: str, email: str | None) -> None:
        with self._db_cursor() as cur:
            if cur is None:
                return

            login_name = self._build_login_name(user_id=user_id, email=email)
            display_name = self._build_display_name(user_id=user_id, email=email)

            cur.execute(
                """
                INSERT INTO users (id, login_name, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  login_name = EXCLUDED.login_name,
                  display_name = EXCLUDED.display_name
                """,
                (user_id, login_name, display_name),
            )

    @staticmethod
    def _build_login_name(user_id: str, email: str | None) -> str:
        if email:
            cleaned = email.strip().lower()
            if cleaned:
                return cleaned[:64]
        return f"user-{user_id}"[:64]

    @staticmethod
    def _build_display_name(user_id: str, email: str | None) -> str:
        if email:
            cleaned = email.strip()
            if cleaned:
                local_name = cleaned.split("@", 1)[0].strip()
                if local_name:
                    return local_name[:64]
        return f"player-{user_id[:8]}"[:64]

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
