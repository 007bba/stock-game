from __future__ import annotations

from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.service.auth import AuthContext, get_current_user


class PlaceOrderBody(BaseModel):
    clientOrderId: str
    accountId: int
    tsCode: str
    side: str
    limitPrice: float
    quantity: int


def create_app(trading_service, tick_provider, quote_provider) -> FastAPI:
    app = FastAPI(title="Stock Game Trading API", version="0.1.0")

    @app.post("/v1/seasons/{seasonId}/join")
    def join_season(seasonId: int, current_user: AuthContext = Depends(get_current_user)):
        try:
            joined = trading_service.join_season(season_id=seasonId, user_id=current_user.user_id)
        except ValueError as exc:
            if str(exc) == "SEASON_NOT_FOUND":
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"code": "SEASON_NOT_FOUND", "message": "season not found"},
                )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "JOIN_SEASON_FAILED", "message": str(exc)},
            )

        return joined

    @app.post("/v1/seasons/{seasonId}/orders")
    def post_order(seasonId: int, body: PlaceOrderBody, current_user: AuthContext = Depends(get_current_user)):
        account = trading_service.state.accounts.get(body.accountId)
        if account is None or account.season_id != seasonId:
            return JSONResponse(
                status_code=400,
                content={"code": "ACCOUNT_NOT_FOUND", "message": "account not found for this season"},
            )

        if str(account.user_id) != current_user.user_id:
            return JSONResponse(
                status_code=403,
                content={"code": "PERMISSION_DENIED", "message": "account does not belong to current user"},
            )

        tick = tick_provider(seasonId)
        quote = quote_provider(seasonId, body.tsCode)

        req = PlaceOrderRequest(
            season_id=seasonId,
            user_id=current_user.user_id,
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
    def get_orders(seasonId: int, status: str | None = None, tsCode: str | None = None, current_user: AuthContext = Depends(get_current_user)):
        return trading_service.list_orders(
            season_id=seasonId,
            user_id=current_user.user_id,
            status=status,
            ts_code=tsCode,
        )

    @app.post("/v1/seasons/{seasonId}/orders/{orderId}/cancel")
    def cancel_order(seasonId: int, orderId: int, current_user: AuthContext = Depends(get_current_user)):
        order = trading_service.state.orders.get(orderId)
        if order is None or order.season_id != seasonId or order.user_id != current_user.user_id:
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
