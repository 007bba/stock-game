import pathlib
import sys
import unittest

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
}


class TestOrderApi(unittest.TestCase):
    def setUp(self):
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

    def test_post_order_returns_201_or_400_with_reject_code(self):
        payload = {
            "clientOrderId": "api-1",
            "userId": "buyer",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 12.0,
            "quantity": 100,
        }
        resp = self.client.post("/v1/seasons/1/orders", json=payload)
        self.assertIn(resp.status_code, (201, 400))
        if resp.status_code == 400:
            body = resp.json()
            self.assertIn("code", body)
            self.assertIn(body["code"], REJECT_CODES)

    def test_post_order_success_contains_contract_fields(self):
        payload = {
            "clientOrderId": "api-success-1",
            "userId": "buyer",
            "accountId": 1,
            "tsCode": "600000.SH",
            "side": "buy",
            "limitPrice": 10.0,
            "quantity": 100,
        }
        resp = self.client.post("/v1/seasons/1/orders", json=payload)
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
                "userId": "buyer",
                "accountId": 1,
                "tsCode": "600000.SH",
                "side": "buy",
                "limitPrice": 10.0,
                "quantity": 100,
            },
        )
        resp = self.client.get("/v1/seasons/1/orders", params={"userId": "buyer"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_cancel_order_returns_200_and_status_canceled(self):
        place_resp = self.client.post(
            "/v1/seasons/1/orders",
            json={
                "clientOrderId": "api-cancel-1",
                "userId": "buyer",
                "accountId": 1,
                "tsCode": "600000.SH",
                "side": "buy",
                "limitPrice": 10.0,
                "quantity": 100,
            },
        )
        self.assertEqual(place_resp.status_code, 201)
        order_id = place_resp.json()["id"]

        cancel_resp = self.client.post(
            f"/v1/seasons/1/orders/{order_id}/cancel",
            params={"userId": "buyer"},
        )
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "canceled")

    def test_cancel_order_not_found_returns_contract_error(self):
        cancel_resp = self.client.post(
            "/v1/seasons/1/orders/999999/cancel",
            params={"userId": "buyer"},
        )
        self.assertEqual(cancel_resp.status_code, 400)
        body = cancel_resp.json()
        self.assertEqual(body["code"], "ORDER_NOT_FOUND")
        self.assertIn(body["code"], REJECT_CODES)


if __name__ == "__main__":
    unittest.main()
