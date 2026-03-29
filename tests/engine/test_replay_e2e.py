import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import EngineOrchestrator, PlaceOrderRequest
from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick


class TestReplayE2E(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryState()
        self.orch = EngineOrchestrator(self.state)

        self.buyer = "user-buyer"
        self.seller = "user-seller"
        self.ts_code = "600000.SH"

        self.state.accounts[1] = Account(
            id=1,
            season_id=1,
            user_id=self.buyer,
            initial_cash=1000000.0,
            available_cash=1000000.0,
            frozen_cash=0.0,
            realized_pnl=0.0,
        )
        self.state.accounts[2] = Account(
            id=2,
            season_id=1,
            user_id=self.seller,
            initial_cash=1000000.0,
            available_cash=1000000.0,
            frozen_cash=0.0,
            realized_pnl=0.0,
        )
        self.state.positions[(1, self.seller, self.ts_code)] = Position(
            season_id=1,
            user_id=self.seller,
            ts_code=self.ts_code,
            qty_total=1000,
            qty_sellable=1000,
            avg_cost=9.5,
            last_settled_game_day=0,
        )

    def _tick(self, tick_id: int, game_day_no: int, is_matching_point: bool, phase: str = "am_continuous"):
        return Tick(
            id=tick_id,
            season_id=1,
            game_day_no=game_day_no,
            minute_of_day=8 if is_matching_point else 7,
            phase=phase,
            matching_mode="batch_match" if is_matching_point else "accept_only",
            is_tradable=True,
            is_matching_point=is_matching_point,
        )

    def _quote(self, halted: bool = False):
        return Quote(
            ts_code=self.ts_code,
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=halted,
        )

    def test_normal_buy_match_and_ledger(self):
        place_tick = self._tick(tick_id=1, game_day_no=1, is_matching_point=False)
        quote = self._quote()

        buy_order = self.orch.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-1",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.2,
                quantity=100,
            ),
        )
        sell_order = self.orch.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.seller,
                account_id=2,
                client_order_id="sell-1",
                ts_code=self.ts_code,
                side="sell",
                limit_price=9.8,
                quantity=100,
            ),
        )

        self.assertEqual(buy_order.status, "active")
        self.assertEqual(sell_order.status, "active")

        match_tick = self._tick(tick_id=2, game_day_no=1, is_matching_point=True)
        trade_ids = self.orch.process_tick(match_tick, {self.ts_code: quote})

        self.assertEqual(len(trade_ids), 1)
        self.assertEqual(self.state.orders[buy_order.id].status, "filled")
        self.assertEqual(self.state.orders[sell_order.id].status, "filled")
        self.assertEqual(len(self.state.trades), 1)
        self.assertEqual(self.state.trades[0].quantity, 100)

        buyer_account = self.state.accounts[1]
        seller_account = self.state.accounts[2]
        self.assertEqual(buyer_account.frozen_cash, 0.0)
        self.assertLess(buyer_account.available_cash, 1000000.0)
        self.assertGreater(seller_account.available_cash, 1000000.0)

        buyer_pos = self.state.get_position(1, self.buyer, self.ts_code)
        seller_pos = self.state.get_position(1, self.seller, self.ts_code)
        self.assertEqual(buyer_pos.qty_total, 100)
        self.assertEqual(buyer_pos.qty_sellable, 0)
        self.assertEqual(seller_pos.qty_total, 900)
        self.assertEqual(seller_pos.qty_sellable, 900)

        self.assertGreaterEqual(len(self.state.cash_ledger), 5)
        entry_types = {entry.entry_type for entry in self.state.cash_ledger}
        self.assertIn("freeze", entry_types)
        self.assertIn("unfreeze", entry_types)
        self.assertIn("trade_buy", entry_types)
        self.assertIn("trade_sell", entry_types)
        self.assertIn("fee", entry_types)

    def test_reject_non_lot_size(self):
        order = self.orch.place_order(
            tick=self._tick(tick_id=10, game_day_no=1, is_matching_point=False),
            quote=self._quote(),
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-lot-invalid",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.0,
                quantity=50,
            ),
        )
        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.reject_code, "LOT_SIZE_INVALID")

    def test_reject_limit_price_out_of_band(self):
        order = self.orch.place_order(
            tick=self._tick(tick_id=11, game_day_no=1, is_matching_point=False),
            quote=self._quote(),
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-band-invalid",
                ts_code=self.ts_code,
                side="buy",
                limit_price=11.5,
                quantity=100,
            ),
        )
        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.reject_code, "LIMIT_PRICE_OUT_OF_BAND")

    def test_reject_sell_t1_blocked(self):
        quote = self._quote()
        place_tick = self._tick(tick_id=20, game_day_no=1, is_matching_point=False)
        self.orch.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-t1-a",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.2,
                quantity=100,
            ),
        )
        self.orch.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.seller,
                account_id=2,
                client_order_id="sell-t1-a",
                ts_code=self.ts_code,
                side="sell",
                limit_price=9.8,
                quantity=100,
            ),
        )

        self.orch.process_tick(self._tick(tick_id=21, game_day_no=1, is_matching_point=True), {self.ts_code: quote})

        t1_sell = self.orch.place_order(
            tick=self._tick(tick_id=22, game_day_no=1, is_matching_point=False),
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="sell-t1-b",
                ts_code=self.ts_code,
                side="sell",
                limit_price=10.0,
                quantity=100,
            ),
        )

        self.assertEqual(t1_sell.status, "rejected")
        self.assertEqual(t1_sell.reject_code, "SELL_T1_BLOCKED")

    def test_reject_stock_halted(self):
        order = self.orch.place_order(
            tick=self._tick(tick_id=30, game_day_no=1, is_matching_point=False),
            quote=self._quote(halted=True),
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-halted",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.0,
                quantity=100,
            ),
        )
        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.reject_code, "STOCK_HALTED")


if __name__ == "__main__":
    unittest.main()
