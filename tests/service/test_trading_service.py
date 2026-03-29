import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick
from scripts.service.trading_service import TradingService


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


if __name__ == "__main__":
    unittest.main()
