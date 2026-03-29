from __future__ import annotations

from dataclasses import asdict

from scripts.engine.orchestrator import EngineOrchestrator, PlaceOrderRequest
from scripts.engine.state import Order, Quote, Tick


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
