import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick
from scripts.service.trading_service import TradingService


class _FakeEventPublisher:
    def __init__(self):
        self.season_events: list[tuple[int, str, dict]] = []
        self.user_events: list[tuple[str, int | None, str, dict]] = []

    def publish_to_season(self, season_id: int, event: str, payload: dict):
        self.season_events.append((season_id, event, payload))
        return {"event": event, "payload": payload}

    def publish_to_user(self, user_id: str, event: str, payload: dict, season_id: int | None = None):
        self.user_events.append((user_id, season_id, event, payload))
        return {"event": event, "payload": payload}


class TestTradingService(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryState()
        self.state.accounts[1] = Account(
            id=1,
            season_id=1,
            user_id="buyer",
            initial_cash=1000000.0,
            available_cash=1000000.0,
            frozen_cash=0.0,
            realized_pnl=0.0,
        )
        self.state.accounts[2] = Account(
            id=2,
            season_id=1,
            user_id="seller",
            initial_cash=1000000.0,
            available_cash=1000000.0,
            frozen_cash=0.0,
            realized_pnl=0.0,
        )
        self.state.positions[(1, "seller", "600000.SH")] = Position(
            season_id=1,
            user_id="seller",
            ts_code="600000.SH",
            qty_total=1000,
            qty_sellable=1000,
            avg_cost=9.5,
            last_settled_game_day=0,
        )
        self.svc = TradingService(self.state)

    def _tick(self, tick_id: int = 1, is_matching_point: bool = False):
        return Tick(
            id=tick_id,
            season_id=1,
            game_day_no=1,
            minute_of_day=8 if is_matching_point else 7,
            phase="am_continuous",
            matching_mode="batch_match" if is_matching_point else "accept_only",
            is_tradable=True,
            is_matching_point=is_matching_point,
        )

    def _quote(self):
        return Quote(
            ts_code="600000.SH",
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=False,
        )

    def test_place_order_returns_reject_code_and_persists_order(self):
        payload = PlaceOrderRequest(
            season_id=1,
            user_id="buyer",
            account_id=1,
            client_order_id="svc-order-1",
            ts_code="600000.SH",
            side="buy",
            limit_price=12.0,
            quantity=100,
        )

        result = self.svc.place_order(tick=self._tick(), quote=self._quote(), req=payload)

        self.assertIn(result["status"], {"active", "rejected"})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["rejectCode"], "LIMIT_PRICE_OUT_OF_BAND")
        self.assertEqual(len(self.state.orders), 1)
        self.assertIn("createdAt", result)
        self.assertIsInstance(result["createdAt"], str)

    def test_join_season_creates_account_and_is_idempotent(self):
        first = self.svc.join_season(season_id=1, user_id="new-user")
        self.assertTrue(first["isNewJoin"])

        second = self.svc.join_season(season_id=1, user_id="new-user")
        self.assertFalse(second["isNewJoin"])
        self.assertEqual(first["accountId"], second["accountId"])

    def test_process_tick_publishes_match_related_events(self):
        publisher = _FakeEventPublisher()
        service = TradingService(self.state, event_publisher=publisher)

        buy_req = PlaceOrderRequest(
            season_id=1,
            user_id="buyer",
            account_id=1,
            client_order_id="buy-for-match",
            ts_code="600000.SH",
            side="buy",
            limit_price=10.0,
            quantity=100,
        )
        sell_req = PlaceOrderRequest(
            season_id=1,
            user_id="seller",
            account_id=2,
            client_order_id="sell-for-match",
            ts_code="600000.SH",
            side="sell",
            limit_price=10.0,
            quantity=100,
        )

        service.place_order(tick=self._tick(), quote=self._quote(), req=buy_req)
        service.place_order(tick=self._tick(), quote=self._quote(), req=sell_req)

        result = service.process_tick(tick=self._tick(tick_id=2, is_matching_point=True), quotes_by_code={"600000.SH": self._quote()})

        self.assertEqual(result["tradeCount"], 1)

        season_event_names = [item[1] for item in publisher.season_events]
        self.assertIn("tick_update", season_event_names)
        self.assertIn("trade_matched", season_event_names)

        buyer_events = [item[2] for item in publisher.user_events if item[0] == "buyer"]
        seller_events = [item[2] for item in publisher.user_events if item[0] == "seller"]

        self.assertIn("order_matched", buyer_events)
        self.assertIn("position_update", buyer_events)
        self.assertIn("account_update", buyer_events)

        self.assertIn("order_matched", seller_events)
        self.assertIn("position_update", seller_events)
        self.assertIn("account_update", seller_events)


if __name__ == "__main__":
    unittest.main()
