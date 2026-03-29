import base64
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick
from scripts.service.api import create_app
from scripts.service.trading_service import TradingService


def _encode_segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def make_test_token(
    user_id: str,
    *,
    audience: str = "authenticated",
    issuer: str = "https://supabase.test/auth/v1",
    exp_offset_seconds: int = 3600,
) -> str:
    secret = os.environ["SUPABASE_JWT_SECRET"]
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "email": f"{user_id}@stock-game.local",
        "aud": audience,
        "iss": issuer,
        "exp": int(time.time()) + exp_offset_seconds,
    }

    encoded_header = _encode_segment(header)
    encoded_payload = _encode_segment(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


class TestWebSocketApi(unittest.TestCase):
    def setUp(self):
        os.environ["SUPABASE_USE_JWKS"] = "false"
        os.environ["SUPABASE_JWT_SECRET"] = "unit-test-secret"
        os.environ["SUPABASE_JWT_ISSUER"] = "https://supabase.test/auth/v1"

        state = InMemoryState()
        state.accounts[1] = Account(
            id=1,
            season_id=1,
            user_id="ws-user",
            initial_cash=1000000.0,
            available_cash=1000000.0,
        )
        state.accounts[2] = Account(
            id=2,
            season_id=1,
            user_id="seller",
            initial_cash=1000000.0,
            available_cash=1000000.0,
        )
        state.positions[(1, "seller", "600000.SH")] = Position(
            season_id=1,
            user_id="seller",
            ts_code="600000.SH",
            qty_total=1000,
            qty_sellable=1000,
            avg_cost=9.5,
            last_settled_game_day=0,
        )
        service = TradingService(state)

        app = create_app(
            trading_service=service,
            tick_provider=lambda season_id: Tick(
                id=1,
                season_id=season_id,
                game_day_no=1,
                minute_of_day=1,
                phase="am_continuous",
                matching_mode="accept_only",
                is_tradable=True,
                is_matching_point=False,
            ),
            quote_provider=lambda season_id, ts_code: Quote(
                ts_code=ts_code,
                ref_price=10.0,
                upper_limit_price=11.0,
                lower_limit_price=9.0,
                is_halted=False,
            ),
            ws_heartbeat_interval_seconds=3600.0,
        )

        self.app = app
        self.state = state
        self.service = service
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("SUPABASE_USE_JWKS", None)
        os.environ.pop("SUPABASE_JWT_SECRET", None)
        os.environ.pop("SUPABASE_JWT_ISSUER", None)

    def test_websocket_rejects_missing_token(self):
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect("/ws/1"):
                pass

        self.assertEqual(ctx.exception.code, 4401)

    def test_websocket_accepts_valid_token_and_sends_heartbeat(self):
        token = make_test_token("ws-user")
        app = create_app(
            trading_service=TradingService(InMemoryState()),
            tick_provider=lambda season_id: Tick(
                id=1,
                season_id=season_id,
                game_day_no=1,
                minute_of_day=1,
                phase="am_continuous",
                matching_mode="accept_only",
                is_tradable=True,
                is_matching_point=False,
            ),
            quote_provider=lambda season_id, ts_code: Quote(
                ts_code=ts_code,
                ref_price=10.0,
                upper_limit_price=11.0,
                lower_limit_price=9.0,
                is_halted=False,
            ),
            ws_heartbeat_interval_seconds=0.05,
        )
        client = TestClient(app)

        with client.websocket_connect(f"/ws/1?token={token}") as ws:
            message = ws.receive_text()
            self.assertEqual(message, "ping")

            ws.send_text("ping")
            self.assertEqual(ws.receive_text(), "pong")

        self.assertEqual(app.state.ws_manager.connection_count(), 0)

    def test_place_order_pushes_rejected_event_to_user(self):
        token = make_test_token("ws-user")
        headers = {"Authorization": f"Bearer {token}"}

        with self.client.websocket_connect(f"/ws/1?token={token}") as ws:
            response = self.client.post(
                "/v1/seasons/1/orders",
                headers=headers,
                json={
                    "clientOrderId": "ws-order-reject-1",
                    "accountId": 1,
                    "tsCode": "600000.SH",
                    "side": "buy",
                    "limitPrice": 12.0,
                    "quantity": 100,
                },
            )
            self.assertEqual(response.status_code, 400)

            message = ws.receive_json()
            self.assertEqual(message["event"], "order_rejected")
            self.assertEqual(message["payload"]["seasonId"], 1)
            self.assertEqual(message["payload"]["accountId"], 1)

    def test_process_tick_pushes_tick_and_match_events(self):
        token = make_test_token("ws-user")

        buy_req = PlaceOrderRequest(
            season_id=1,
            user_id="ws-user",
            account_id=1,
            client_order_id="ws-buy-1",
            ts_code="600000.SH",
            side="buy",
            limit_price=10.0,
            quantity=100,
        )
        sell_req = PlaceOrderRequest(
            season_id=1,
            user_id="seller",
            account_id=2,
            client_order_id="ws-sell-1",
            ts_code="600000.SH",
            side="sell",
            limit_price=10.0,
            quantity=100,
        )

        quote = Quote(
            ts_code="600000.SH",
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=False,
        )
        self.service.place_order(
            tick=Tick(
                id=1,
                season_id=1,
                game_day_no=1,
                minute_of_day=7,
                phase="am_continuous",
                matching_mode="accept_only",
                is_tradable=True,
                is_matching_point=False,
            ),
            quote=quote,
            req=buy_req,
        )
        self.service.place_order(
            tick=Tick(
                id=1,
                season_id=1,
                game_day_no=1,
                minute_of_day=7,
                phase="am_continuous",
                matching_mode="accept_only",
                is_tradable=True,
                is_matching_point=False,
            ),
            quote=quote,
            req=sell_req,
        )

        with self.client.websocket_connect(f"/ws/1?token={token}") as ws:
            self.service.process_tick(
                tick=Tick(
                    id=2,
                    season_id=1,
                    game_day_no=1,
                    minute_of_day=8,
                    phase="am_continuous",
                    matching_mode="batch_match",
                    is_tradable=True,
                    is_matching_point=True,
                ),
                quotes_by_code={"600000.SH": quote},
            )

            first_user_event = ws.receive_json()
            self.assertIn(first_user_event["event"], {"order_matched", "position_update", "account_update", "tick_update", "trade_matched"})

        latest_events = self.app.state.event_publisher.latest(limit=20)
        latest_names = {item["event"] for item in latest_events}
        self.assertIn("tick_update", latest_names)
        self.assertIn("trade_matched", latest_names)
        self.assertIn("order_matched", latest_names)
        self.assertIn("position_update", latest_names)
        self.assertIn("account_update", latest_names)


if __name__ == "__main__":
    unittest.main()
