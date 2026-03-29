from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from scripts.engine.orchestrator import PlaceOrderRequest


class PlaceOrderBody(BaseModel):
    clientOrderId: str
    userId: str
    accountId: int
    tsCode: str
    side: str
    limitPrice: float
    quantity: int


def create_app(trading_service, tick_provider, quote_provider) -> FastAPI:
    app = FastAPI(title="Stock Game Trading API", version="0.1.0")

    @app.post("/v1/seasons/{seasonId}/orders")
    def post_order(seasonId: int, body: PlaceOrderBody):
        tick = tick_provider(seasonId)
        quote = quote_provider(seasonId, body.tsCode)

        req = PlaceOrderRequest(
            season_id=seasonId,
            user_id=body.userId,
            account_id=body.accountId,
            client_order_id=body.clientOrderId,
            ts_code=body.tsCode,
            side=body.side,
            limit_price=body.limitPrice,
            quantity=body.quantity,
        )
        result = trading_service.place_order(tick=tick, quote=quote, req=req)
        if result["status"] == "rejected":
            return JSONResponse(
                status_code=400,
                content={
                    "code": result.get("rejectCode"),
                    "message": result.get("rejectReason") or "order rejected",
                },
            )
        return JSONResponse(status_code=201, content=result)

    @app.get("/v1/seasons/{seasonId}/orders")
    def get_orders(seasonId: int, userId: str, status: str | None = None, tsCode: str | None = None):
        return trading_service.list_orders(season_id=seasonId, user_id=userId, status=status, ts_code=tsCode)

    @app.post("/v1/seasons/{seasonId}/orders/{orderId}/cancel")
    def cancel_order(seasonId: int, orderId: int, userId: str):
        order = trading_service.state.orders.get(orderId)
        if order is None or order.season_id != seasonId or order.user_id != userId:
            return JSONResponse(
                status_code=400,
                content={"code": "ORDER_NOT_FOUND", "message": "order not found"},
            )

        if order.status not in {"active", "partially_filled"}:
            return JSONResponse(
                status_code=400,
                content={"code": "ORDER_NOT_CANCELABLE", "message": f"order status={order.status} cannot be canceled"},
            )

        with trading_service.state.transaction():
            order.status = "canceled"
            order.updated_at = trading_service.state.now()

        return trading_service._order_to_dto(order)

    return app
