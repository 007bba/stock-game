from __future__ import annotations

import asyncio
import contextlib

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.service.auth import AuthContext, get_current_user, get_current_user_ws
from scripts.service.event_publisher import EventPublisher
from scripts.service.websocket_manager import ConnectionManager


class PlaceOrderBody(BaseModel):
    clientOrderId: str
    accountId: int
    tsCode: str
    side: str
    limitPrice: float
    quantity: int


def create_app(
    trading_service,
    tick_provider,
    quote_provider,
    ws_manager: ConnectionManager | None = None,
    event_publisher: EventPublisher | None = None,
    ws_heartbeat_interval_seconds: float = 30.0,
) -> FastAPI:
    app = FastAPI(title="Stock Game Trading API", version="0.1.0")
    manager = ws_manager or ConnectionManager()
    publisher = event_publisher or EventPublisher(ws_manager=manager)
    heartbeat_interval_seconds = ws_heartbeat_interval_seconds
    app.state.ws_manager = manager
    app.state.event_publisher = publisher

    if hasattr(trading_service, "set_event_publisher"):
        trading_service.set_event_publisher(publisher)

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
            publisher.publish_to_user(
                user_id=current_user.user_id,
                season_id=seasonId,
                event="order_rejected",
                payload={
                    "seasonId": seasonId,
                    "orderId": result.get("id"),
                    "accountId": body.accountId,
                    "rejectCode": result.get("rejectCode"),
                    "rejectReason": result.get("rejectReason"),
                },
            )
            return JSONResponse(
                status_code=400,
                content={
                    "code": result.get("rejectCode"),
                    "message": result.get("rejectReason") or "order rejected",
                },
            )

        publisher.publish_to_user(
            user_id=current_user.user_id,
            season_id=seasonId,
            event="order_updated",
            payload={
                "seasonId": seasonId,
                "accountId": body.accountId,
                "order": result,
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

        dto = trading_service._order_to_dto(order)
        publisher.publish_to_user(
            user_id=current_user.user_id,
            season_id=seasonId,
            event="order_updated",
            payload={
                "seasonId": seasonId,
                "accountId": order.account_id,
                "order": dto,
            },
        )
        return dto

    @app.websocket("/ws/{seasonId}")
    async def websocket_endpoint(websocket: WebSocket, seasonId: int):
        token = _extract_ws_token(websocket)
        user = get_current_user_ws(token)
        if user is None:
            await websocket.close(code=4401, reason="Unauthorized")
            return

        await manager.connect(websocket=websocket, season_id=seasonId, user_id=user.user_id)
        heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket, interval_seconds=heartbeat_interval_seconds))

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                text = message.get("text")
                if text is None:
                    continue

                payload = text.strip().lower()
                if payload == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            await manager.disconnect(websocket)

    return app


def _extract_ws_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token

    authorization = websocket.headers.get("authorization")
    if not authorization:
        return None

    value = authorization.strip()
    if not value.lower().startswith("bearer "):
        return None

    return value[7:].strip() or None


async def _heartbeat_loop(websocket: WebSocket, interval_seconds: float):
    if interval_seconds <= 0:
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await websocket.send_text("ping")
        except Exception:
            return
