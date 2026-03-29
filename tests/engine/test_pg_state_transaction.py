import os
import pathlib
import sys
import unittest
import uuid
from unittest import mock

from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import EngineOrchestrator, PlaceOrderRequest
from scripts.engine.state import Account, InMemoryState, Position, Quote, Tick

try:
    from scripts.engine.pg_state import PgState
except Exception:  # pragma: no cover
    PgState = None


class TestProcessTickExceptionContract(unittest.TestCase):
    def setUp(self):
        self.state = InMemoryState()
        self.orch = EngineOrchestrator(self.state)
        self.ts_code = "600000.SH"
        self.buyer = "user-buyer"
        self.seller = "user-seller"

        self.state.accounts[1] = Account(id=1, season_id=1, user_id=self.buyer, initial_cash=1000000, available_cash=1000000)
        self.state.accounts[2] = Account(id=2, season_id=1, user_id=self.seller, initial_cash=1000000, available_cash=1000000)
        self.state.positions[(1, self.seller, self.ts_code)] = Position(
            season_id=1,
            user_id=self.seller,
            ts_code=self.ts_code,
            qty_total=1000,
            qty_sellable=1000,
            avg_cost=9.5,
            last_settled_game_day=0,
        )

    def _tick(self, tick_id: int, is_matching_point: bool) -> Tick:
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

    def _quote(self) -> Quote:
        return Quote(
            ts_code=self.ts_code,
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=False,
        )

    def test_process_tick_wraps_exception_and_keeps_state(self):
        place_tick = self._tick(tick_id=1, is_matching_point=False)
        quote = self._quote()

        self.orch.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=1,
                user_id=self.buyer,
                account_id=1,
                client_order_id="buy-x",
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
                client_order_id="sell-x",
                ts_code=self.ts_code,
                side="sell",
                limit_price=9.8,
                quantity=100,
            ),
        )

        baseline_order_remaining = {oid: order.remaining_qty for oid, order in self.state.orders.items()}
        baseline_trades = len(self.state.trades)

        with mock.patch("scripts.engine.matcher.run_batch_match", side_effect=ValueError("forced matching failure")):
            with self.assertRaises(RuntimeError) as raised:
                self.orch.process_tick(self._tick(tick_id=2, is_matching_point=True), {self.ts_code: quote})

        self.assertIsInstance(raised.exception.__cause__, ValueError)
        self.assertEqual(len(self.state.trades), baseline_trades)
        self.assertEqual(
            {oid: order.remaining_qty for oid, order in self.state.orders.items()},
            baseline_order_remaining,
        )
        self.assertTrue(self.state.error_log)


@unittest.skipIf(PgState is None, "psycopg2 is not installed")
class TestPgStateRollbackIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("RUN_DB_INTEGRATION") != "1":
            raise unittest.SkipTest("set RUN_DB_INTEGRATION=1 to enable DB integration tests")

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise unittest.SkipTest("DATABASE_URL is required for pg rollback integration test")

        cls.engine = create_engine(database_url, future=True)
        cls.season_code = f"PGTX-{uuid.uuid4().hex[:12].upper()}"
        cls.user_a = uuid.uuid4()
        cls.user_b = uuid.uuid4()
        cls.ts_code = "600000.SH"
        cls.season_id = None
        cls.tick_place_id = None
        cls.tick_match_id = None

        cls._seed_fixture()

    @classmethod
    def tearDownClass(cls):
        if not hasattr(cls, "engine"):
            return

        with cls.engine.begin() as conn:
            if cls.season_id is not None:
                conn.execute(text("DELETE FROM cash_ledger WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM trades WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM orders WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM positions WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM accounts WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM market_tick_quotes WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM market_ticks WHERE season_id = :sid"), {"sid": cls.season_id})
                conn.execute(text("DELETE FROM seasons WHERE id = :sid"), {"sid": cls.season_id})
            conn.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": str(cls.user_a), "b": str(cls.user_b)})

    @classmethod
    def _seed_fixture(cls):
        with cls.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO seasons (season_code, season_name, status, total_game_days, day_minutes)
                    VALUES (:code, :name, 'running', 1, 60)
                    RETURNING id
                    """
                ),
                {"code": cls.season_code, "name": "Pg Tx Test"},
            ).fetchone()
            cls.season_id = int(row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO users (id, login_name, display_name)
                    VALUES (:id, :login, :name)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                [
                    {"id": str(cls.user_a), "login": f"pgtx-a-{cls.season_id}", "name": "PGA"},
                    {"id": str(cls.user_b), "login": f"pgtx-b-{cls.season_id}", "name": "PGB"},
                ],
            )

            conn.execute(
                text(
                    """
                    INSERT INTO accounts (season_id, user_id, initial_cash, available_cash, frozen_cash)
                    VALUES (:season_id, :user_id, 1000000, 1000000, 0)
                    ON CONFLICT (season_id, user_id) DO NOTHING
                    """
                ),
                [
                    {"season_id": cls.season_id, "user_id": str(cls.user_a)},
                    {"season_id": cls.season_id, "user_id": str(cls.user_b)},
                ],
            )

            conn.execute(
                text(
                    """
                    INSERT INTO positions (season_id, user_id, ts_code, qty_total, qty_sellable, avg_cost, last_settled_game_day)
                    VALUES (:season_id, :user_id, :ts_code, 1000, 1000, 9.5000, 0)
                    ON CONFLICT (season_id, user_id, ts_code) DO NOTHING
                    """
                ),
                {"season_id": cls.season_id, "user_id": str(cls.user_b), "ts_code": cls.ts_code},
            )

            row = conn.execute(
                text(
                    """
                    INSERT INTO market_ticks (
                      season_id, game_day_no, minute_of_day, phase, matching_mode, is_tradable, is_matching_point, scheduled_at
                    ) VALUES (
                      :sid, 1, 7, CAST('am_continuous' AS session_phase), CAST('accept_only' AS matching_mode), TRUE, FALSE, now()
                    ) RETURNING id
                    """
                ),
                {"sid": cls.season_id},
            ).fetchone()
            cls.tick_place_id = int(row[0])

            row = conn.execute(
                text(
                    """
                    INSERT INTO market_ticks (
                      season_id, game_day_no, minute_of_day, phase, matching_mode, is_tradable, is_matching_point, scheduled_at
                    ) VALUES (
                      :sid, 1, 8, CAST('am_continuous' AS session_phase), CAST('batch_match' AS matching_mode), TRUE, TRUE, now()
                    ) RETURNING id
                    """
                ),
                {"sid": cls.season_id},
            ).fetchone()
            cls.tick_match_id = int(row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO market_tick_quotes (
                      tick_id, season_id, ts_code, ref_price, upper_limit_price, lower_limit_price, is_halted, volume, volume_factor
                    ) VALUES (
                      :tick_id, :season_id, :ts_code, 10.000, 11.000, 9.000, FALSE, 0, 1.0
                    )
                    ON CONFLICT (tick_id, ts_code) DO NOTHING
                    """
                ),
                {"tick_id": cls.tick_match_id, "season_id": cls.season_id, "ts_code": cls.ts_code},
            )

    def test_pg_state_rolls_back_on_matching_error(self):
        state = PgState()
        state.load_season_state(self.season_id)
        orch = EngineOrchestrator(state)

        quote = Quote(ts_code=self.ts_code, ref_price=10.0, upper_limit_price=11.0, lower_limit_price=9.0, is_halted=False)
        place_tick = Tick(
            id=self.tick_place_id,
            season_id=self.season_id,
            game_day_no=1,
            minute_of_day=7,
            phase="am_continuous",
            matching_mode="accept_only",
            is_tradable=True,
            is_matching_point=False,
        )
        match_tick = Tick(
            id=self.tick_match_id,
            season_id=self.season_id,
            game_day_no=1,
            minute_of_day=8,
            phase="am_continuous",
            matching_mode="batch_match",
            is_tradable=True,
            is_matching_point=True,
        )

        account_map = {acc.user_id: acc.id for acc in state.accounts.values()}
        orch.place_order(
            place_tick,
            quote,
            PlaceOrderRequest(
                season_id=self.season_id,
                user_id=str(self.user_a),
                account_id=account_map[str(self.user_a)],
                client_order_id="pg-buy-1",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.2,
                quantity=100,
            ),
        )
        orch.place_order(
            place_tick,
            quote,
            PlaceOrderRequest(
                season_id=self.season_id,
                user_id=str(self.user_b),
                account_id=account_map[str(self.user_b)],
                client_order_id="pg-sell-1",
                ts_code=self.ts_code,
                side="sell",
                limit_price=9.8,
                quantity=100,
            ),
        )

        with self.engine.connect() as conn:
            baseline_trades = conn.execute(text("SELECT COUNT(*) FROM trades WHERE season_id = :sid"), {"sid": self.season_id}).scalar_one()
            baseline_statuses = conn.execute(
                text("SELECT status, remaining_qty FROM orders WHERE season_id = :sid ORDER BY id"),
                {"sid": self.season_id},
            ).fetchall()

        with mock.patch("scripts.engine.matcher.run_batch_match", side_effect=ValueError("forced matching failure")):
            with self.assertRaises(RuntimeError):
                orch.process_tick(match_tick, {self.ts_code: quote})

        with self.engine.connect() as conn:
            after_trades = conn.execute(text("SELECT COUNT(*) FROM trades WHERE season_id = :sid"), {"sid": self.season_id}).scalar_one()
            after_statuses = conn.execute(
                text("SELECT status, remaining_qty FROM orders WHERE season_id = :sid ORDER BY id"),
                {"sid": self.season_id},
            ).fetchall()

        self.assertEqual(after_trades, baseline_trades)
        self.assertEqual(after_statuses, baseline_statuses)


if __name__ == "__main__":
    unittest.main()
