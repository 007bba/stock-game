import os
import pathlib
import sys
import unittest
import uuid

from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.orchestrator import PlaceOrderRequest
from scripts.engine.state import Quote, Tick
from scripts.service.events import EventBus
from scripts.service.season_scheduler import SeasonScheduler, build_db_quote_loader, build_db_tick_loader
from scripts.service.trading_service import TradingService

try:
    from scripts.engine.pg_state import PgState
except Exception:  # pragma: no cover
    PgState = None


@unittest.skipIf(PgState is None, "psycopg2 is not installed")
class TestTradeReplayDbFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("RUN_DB_INTEGRATION") != "1":
            raise unittest.SkipTest("set RUN_DB_INTEGRATION=1 to enable DB integration tests")

        cls.database_url = os.getenv("DATABASE_URL")
        if not cls.database_url:
            raise unittest.SkipTest("DATABASE_URL is required for DB integration tests")

        cls.engine = create_engine(cls.database_url, future=True)
        cls.season_code = f"P5FLOW-{uuid.uuid4().hex[:8].upper()}"
        cls.user_buyer = uuid.uuid4()
        cls.user_seller = uuid.uuid4()
        cls.ts_code = "600000.SH"

        cls.season_id = None
        cls.tick_place_id = None
        cls.tick_match_id = None
        cls.account_buyer_id = None
        cls.account_seller_id = None

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
            conn.execute(text("DELETE FROM users WHERE id IN (:buyer, :seller)"), {"buyer": str(cls.user_buyer), "seller": str(cls.user_seller)})

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
                {"code": cls.season_code, "name": "P5 Replay Flow"},
            ).fetchone()
            cls.season_id = int(row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO users (id, login_name, display_name)
                    VALUES (:id, :login, :display)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                [
                    {"id": str(cls.user_buyer), "login": f"p5-buyer-{cls.season_id}", "display": "P5 Buyer"},
                    {"id": str(cls.user_seller), "login": f"p5-seller-{cls.season_id}", "display": "P5 Seller"},
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
                    {"season_id": cls.season_id, "user_id": str(cls.user_buyer)},
                    {"season_id": cls.season_id, "user_id": str(cls.user_seller)},
                ],
            )

            rows = conn.execute(
                text("SELECT id, user_id FROM accounts WHERE season_id = :sid"),
                {"sid": cls.season_id},
            ).fetchall()
            for row in rows:
                if str(row[1]) == str(cls.user_buyer):
                    cls.account_buyer_id = int(row[0])
                if str(row[1]) == str(cls.user_seller):
                    cls.account_seller_id = int(row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO positions (season_id, user_id, ts_code, qty_total, qty_sellable, avg_cost, last_settled_game_day)
                    VALUES (:sid, :uid, :ts_code, 1000, 1000, 9.5000, 0)
                    ON CONFLICT (season_id, user_id, ts_code) DO NOTHING
                    """
                ),
                {"sid": cls.season_id, "uid": str(cls.user_seller), "ts_code": cls.ts_code},
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
                      :tick_id, :season_id, :ts_code, 10.000, 11.000, 9.000, FALSE, 10000, 1.0
                    )
                    ON CONFLICT (tick_id, ts_code) DO NOTHING
                    """
                ),
                {"tick_id": cls.tick_match_id, "season_id": cls.season_id, "ts_code": cls.ts_code},
            )

    def test_db_flow_order_match_ledger_consistency(self):
        state = PgState(database_url=self.database_url)
        trading_service = TradingService(state=state, season_id=self.season_id)
        event_bus = EventBus()

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
        quote = Quote(
            ts_code=self.ts_code,
            ref_price=10.0,
            upper_limit_price=11.0,
            lower_limit_price=9.0,
            is_halted=False,
        )

        trading_service.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=self.season_id,
                user_id=str(self.user_buyer),
                account_id=self.account_buyer_id,
                client_order_id="flow-buy-1",
                ts_code=self.ts_code,
                side="buy",
                limit_price=10.2,
                quantity=100,
            ),
        )
        trading_service.place_order(
            tick=place_tick,
            quote=quote,
            req=PlaceOrderRequest(
                season_id=self.season_id,
                user_id=str(self.user_seller),
                account_id=self.account_seller_id,
                client_order_id="flow-sell-1",
                ts_code=self.ts_code,
                side="sell",
                limit_price=9.8,
                quantity=100,
            ),
        )

        scheduler = SeasonScheduler(
            trading_service=trading_service,
            tick_loader=build_db_tick_loader(self.database_url),
            quote_loader=build_db_quote_loader(self.database_url),
            checkpoint_file=None,
            event_bus=event_bus,
        )

        result = scheduler.run_once(season_id=self.season_id)
        self.assertGreaterEqual(result["matching_ticks"], 1)

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, remaining_qty, client_order_id FROM orders WHERE season_id = :sid ORDER BY id"
                ),
                {"sid": self.season_id},
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({str(row[0]) for row in rows}, {"filled"})
            self.assertEqual({int(row[1]) for row in rows}, {0})

            trade_count = conn.execute(text("SELECT COUNT(*) FROM trades WHERE season_id = :sid"), {"sid": self.season_id}).scalar_one()
            self.assertEqual(int(trade_count), 1)

            buyer_pos = conn.execute(
                text(
                    "SELECT qty_total, qty_sellable FROM positions WHERE season_id = :sid AND user_id = :uid AND ts_code = :ts_code"
                ),
                {"sid": self.season_id, "uid": str(self.user_buyer), "ts_code": self.ts_code},
            ).fetchone()
            self.assertEqual(int(buyer_pos[0]), 100)
            self.assertEqual(int(buyer_pos[1]), 0)

            seller_pos = conn.execute(
                text(
                    "SELECT qty_total, qty_sellable FROM positions WHERE season_id = :sid AND user_id = :uid AND ts_code = :ts_code"
                ),
                {"sid": self.season_id, "uid": str(self.user_seller), "ts_code": self.ts_code},
            ).fetchone()
            self.assertEqual(int(seller_pos[0]), 900)
            self.assertEqual(int(seller_pos[1]), 900)

            ledger_count = conn.execute(
                text("SELECT COUNT(*) FROM cash_ledger WHERE season_id = :sid"),
                {"sid": self.season_id},
            ).scalar_one()
            self.assertGreaterEqual(int(ledger_count), 5)

        latest_events = event_bus.latest(limit=20)
        self.assertTrue(any(item["event"] == "trade.matched" for item in latest_events))


if __name__ == "__main__":
    unittest.main()
