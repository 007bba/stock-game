import pathlib
import sys
import unittest
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick
from scripts.service.api import create_app
from scripts.service.trading_service import TradingService


REJECT_CODES = {
    "LOT_SIZE_INVALID",
    "LIMIT_PRICE_OUT_OF_BAND",
    "SELL_T1_BLOCKED",
    "INSUFFICIENT_SELLABLE_QTY",
    "STOCK_HALTED",
    "SEASON_NOT_TRADING",
    "AUCTION_WINDOW_CLOSED",
    "INSUFFICIENT_CASH",
    "ORDER_NOT_FOUND",
    "ORDER_NOT_CANCELABLE",
    "ACCOUNT_NOT_FOUND",
    "PERMISSION_DENIED",
}


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


class TestOrderApi(unittest.TestCase):
    def setUp(self):
        os.environ["SUPABASE_JWT_SECRET"] = "unit-test-secret"
        os.environ["SUPABASE_JWT_ISSUER"] = "https://supabase.test/auth/v1"

        self.state = InMemoryState()
        self.state.accounts[1] = Account(id=1, season_id=1, user_id="buyer", initial_cash=1000000, available_cash=1000000)
        self.state.accounts[2] = Account(id=2, season_id=1, user_id="seller", initial_cash=1000000, available_cash=1000000)
        self.state.positions[(1, "seller", "600000.SH")] = Position(
            season_id=1,
            user_id="seller",
            ts_code="600000.SH",
            qty_total=1000,
            qty_sellable=1000,
            avg_cost=9.5,
            last_settled_game_day=0,
        )
        self.service = TradingService(self.state)

        self.tick = Tick(
            id=1,
            season_id=1,
            game_day_no=1,
            minute_of_day=7,
            phase="am_continuous",
            matching_mode="accept_only",
            is_tradable=True,
            is_matching_point=False,
        )
        self.quote = Quote(
            ts_code="600000.SH",
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=False,
        )

        app = create_app(
            trading_service=self.service,
            tick_provider=lambda season_id: self.tick,
            quote_provider=lambda season_id, ts_code: self.quote,
        )
        self.client = TestClient(app)
        self.buyer_headers = {"Authorization": f"Bearer {make_test_token('buyer')}"}

    def tearDown(self):
        os.environ.pop("SUPABASE_JWT_SECRET", None)
        os.environ.pop("SUPABASE_JWT_ISSUER", None)

    def test_post_order_requires_bearer_token(self):
        payload = {
            "clientOrderId": "api-no-token",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 10.0,
            "quantity": 100,
        }
        resp = self.client.post("/v1/seasons/1/orders", json=payload)
        self.assertEqual(resp.status_code, 401)

    def test_join_season_requires_bearer_token(self):
        resp = self.client.post("/v1/seasons/1/join")
        self.assertEqual(resp.status_code, 401)

    def test_join_season_rejects_invalid_audience(self):
        headers = {"Authorization": f"Bearer {make_test_token('buyer', audience='guest')}"}
        resp = self.client.post("/v1/seasons/1/join", headers=headers)
        self.assertEqual(resp.status_code, 401)

    def test_join_season_is_idempotent_and_returns_same_account(self):
        user_headers = {"Authorization": f"Bearer {make_test_token('newbie')}"}

        first = self.client.post("/v1/seasons/1/join", headers=user_headers)
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertTrue(first_body["isNewJoin"])

        second = self.client.post("/v1/seasons/1/join", headers=user_headers)
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertFalse(second_body["isNewJoin"])
        self.assertEqual(first_body["accountId"], second_body["accountId"])

        account_id = first_body["accountId"]
        self.assertIn(account_id, self.state.accounts)
        self.assertEqual(self.state.accounts[account_id].user_id, "newbie")

    def test_post_order_rejects_invalid_audience(self):
        payload = {
            "clientOrderId": "api-bad-aud",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 10.0,
            "quantity": 100,
        }
        headers = {"Authorization": f"Bearer {make_test_token('buyer', audience='guest')}"}
        resp = self.client.post("/v1/seasons/1/orders", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 401)

    def test_post_order_forbidden_when_account_not_owned(self):
        payload = {
            "clientOrderId": "api-permission-denied",
            "accountId": 2,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 10.0,
            "quantity": 100,
        }

        resp = self.client.post("/v1/seasons/1/orders", json=payload, headers=self.buyer_headers)
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body["code"], "PERMISSION_DENIED")

    def test_post_order_returns_201_or_400_with_reject_code(self):
        payload = {
            "clientOrderId": "api-1",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 12.0,
            "quantity": 100,
        }
        resp = self.client.post("/v1/seasons/1/orders", json=payload, headers=self.buyer_headers)
        self.assertIn(resp.status_code, (201, 400))
        if resp.status_code == 400:
            body = resp.json()
            self.assertIn("code", body)
            self.assertIn(body["code"], REJECT_CODES)

    def test_post_order_success_contains_contract_fields(self):
        payload = {
            "clientOrderId": "api-success-1",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 10.0,
            "quantity": 100,
        }
        resp = self.client.post("/v1/seasons/1/orders", json=payload, headers=self.buyer_headers)
        self.assertEqual(resp.status_code, 201)

        body = resp.json()
        required_keys = {
            "id",
            "clientOrderId",
            "tsCode",
            "side",
            "limitPrice",
            "quantity",
            "remainingQty",
            "status",
            "createdAt",
        }
        self.assertTrue(required_keys.issubset(set(body.keys())))
        self.assertIsInstance(body["createdAt"], str)

    def test_get_orders_returns_list(self):
        self.client.post(
            "/v1/seasons/1/orders",
            json={
                "clientOrderId": "api-2",
                "accountId": 1,
                "tsCode": "600000.SH",
                "side": "buy",
                "limitPrice": 10.0,
                "quantity": 100,
            },
            headers=self.buyer_headers,
        )
        resp = self.client.get("/v1/seasons/1/orders", headers=self.buyer_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_cancel_order_returns_200_and_status_canceled(self):
        place_resp = self.client.post(
            "/v1/seasons/1/orders",
            json={
                "clientOrderId": "api-cancel-1",
                "accountId": 1,
                "tsCode": "600000.SH",
                "side": "buy",
                "limitPrice": 10.0,
                "quantity": 100,
            },
            headers=self.buyer_headers,
        )
        self.assertEqual(place_resp.status_code, 201)
        order_id = place_resp.json()["id"]

        cancel_resp = self.client.post(
            f"/v1/seasons/1/orders/{order_id}/cancel",
            headers=self.buyer_headers,
        )
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "canceled")

    def test_cancel_order_not_found_returns_contract_error(self):
        cancel_resp = self.client.post(
            "/v1/seasons/1/orders/999999/cancel",
            headers=self.buyer_headers,
        )
        self.assertEqual(cancel_resp.status_code, 400)
        body = cancel_resp.json()
        self.assertEqual(body["code"], "ORDER_NOT_FOUND")
        self.assertIn(body["code"], REJECT_CODES)


if __name__ == "__main__":
    unittest.main()
