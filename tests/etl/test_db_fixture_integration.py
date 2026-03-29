import json
import os
import pathlib
import sys
import unittest
from datetime import datetime, timezone

import pandas as pd
import psycopg2
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[2]
ETL_PATH = ROOT / "scripts" / "etl"
if str(ETL_PATH) not in sys.path:
    sys.path.insert(0, str(ETL_PATH))

import tushare_pipeline as tp
import validate_compression as vc


class TestDBFixtureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("RUN_DB_INTEGRATION") != "1":
            raise unittest.SkipTest("set RUN_DB_INTEGRATION=1 to enable DB integration tests")

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise unittest.SkipTest("DATABASE_URL is required for DB integration tests")

        fixture_path = ROOT / "tests" / "fixtures" / "minimal_season_fixture.json"
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        cls.engine = create_engine(database_url, future=True)

        try:
            with cls.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except (psycopg2.OperationalError, OSError) as e:
            raise unittest.SkipTest(f"Skipping DB integration tests — cannot connect: {e}")

        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        cls.season_code = f"ITEST-{suffix}"
        cls.season_name = f"Integration Fixture {suffix}"
        cls.ts_code = cls.fixture["ts_code"]
        cls.exchange = cls.fixture["exchange"]
        cls.market_date = cls.fixture["market_date"]
        cls.season_id = None

        cls._insert_fixture_rows()
        cls._run_compress_and_validate()

    @classmethod
    def tearDownClass(cls):
        if not hasattr(cls, "engine"):
            return

        with cls.engine.begin() as conn:
            if cls.season_id is not None:
                conn.execute(text("DELETE FROM market_tick_quotes WHERE season_id = :season_id"), {"season_id": cls.season_id})
                conn.execute(text("DELETE FROM market_ticks WHERE season_id = :season_id"), {"season_id": cls.season_id})
                conn.execute(text("DELETE FROM etl_jobs WHERE season_id = :season_id"), {"season_id": cls.season_id})
                conn.execute(text("DELETE FROM season_universe WHERE season_id = :season_id"), {"season_id": cls.season_id})
                conn.execute(text("DELETE FROM seasons WHERE id = :season_id"), {"season_id": cls.season_id})

            conn.execute(text("DELETE FROM raw_minute_bars WHERE ts_code = :ts_code"), {"ts_code": cls.ts_code})
            conn.execute(
                text("DELETE FROM trading_calendar WHERE exchange = :exchange AND cal_date = :cal_date"),
                {"exchange": cls.exchange, "cal_date": cls.market_date},
            )

    @classmethod
    def _insert_fixture_rows(cls):
        with cls.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO seasons (season_code, season_name, status, total_game_days, day_minutes)
                    VALUES (:season_code, :season_name, 'draft', 1, 60)
                    RETURNING id
                    """
                ),
                {"season_code": cls.season_code, "season_name": cls.season_name},
            ).fetchone()
            cls.season_id = int(row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO season_universe (season_id, ts_code, role, event_tag, rank_in_theme, is_active)
                    VALUES (:season_id, :ts_code, CAST(:role AS market_role), :event_tag, :rank_in_theme, TRUE)
                    """
                ),
                {
                    "season_id": cls.season_id,
                    "ts_code": cls.ts_code,
                    "role": cls.fixture["role"],
                    "event_tag": cls.fixture["event_tag"],
                    "rank_in_theme": cls.fixture["rank_in_theme"],
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO trading_calendar (exchange, cal_date, is_open, pretrade_date)
                    VALUES (:exchange, :cal_date, TRUE, :cal_date)
                    ON CONFLICT (exchange, cal_date)
                    DO UPDATE SET is_open = EXCLUDED.is_open, pretrade_date = EXCLUDED.pretrade_date
                    """
                ),
                {"exchange": cls.exchange, "cal_date": cls.market_date},
            )

            am_times = pd.date_range(f"{cls.market_date} 09:30:00+08:00", periods=120, freq="min")
            pm_times = pd.date_range(f"{cls.market_date} 13:00:00+08:00", periods=120, freq="min")
            minute_times = list(am_times) + list(pm_times)

            price = 10.0
            for idx, ts_local in enumerate(minute_times):
                close_p = price * 1.0008
                high_p = max(price, close_p)
                low_p = min(price, close_p)

                if idx == 60:
                    high_p = max(high_p, 10.8)
                if idx == 180:
                    low_p = min(low_p, 9.6)

                conn.execute(
                    text(
                        """
                        INSERT INTO raw_minute_bars (
                          ts_code, trade_time, trade_date,
                          open_price, high_price, low_price, close_price,
                          vol, amount, source_name
                        ) VALUES (
                          :ts_code, :trade_time, :trade_date,
                          :open_price, :high_price, :low_price, :close_price,
                          :vol, :amount, 'fixture'
                        )
                        ON CONFLICT (ts_code, trade_time)
                        DO UPDATE SET
                          open_price = EXCLUDED.open_price,
                          high_price = EXCLUDED.high_price,
                          low_price = EXCLUDED.low_price,
                          close_price = EXCLUDED.close_price,
                          vol = EXCLUDED.vol,
                          amount = EXCLUDED.amount,
                          source_name = EXCLUDED.source_name
                        """
                    ),
                    {
                        "ts_code": cls.ts_code,
                        "trade_time": ts_local.tz_convert("UTC").to_pydatetime(),
                        "trade_date": pd.to_datetime(cls.market_date).date(),
                        "open_price": float(price),
                        "high_price": float(high_p),
                        "low_price": float(low_p),
                        "close_price": float(close_p),
                        "vol": 1000,
                        "amount": 1000 * ((price + close_p) / 2),
                    },
                )
                price = close_p

    @classmethod
    def _run_compress_and_validate(cls):
        cfg = tp.Config(
            season_id=cls.season_id,
            start_date=cls.market_date,
            end_date=cls.market_date,
            mode="compress",
            exchange=cls.exchange,
        )
        tp.compress_season(cfg)

        result = vc.validate_db(cls.season_id)
        if not result.ok():
            raise AssertionError(f"fixture validation failed: {result.errors}")

    def test_fixture_counts(self):
        expected_ticks = int(self.fixture["expected"]["ticks"])
        expected_quotes = int(self.fixture["expected"]["quotes"])

        with self.engine.connect() as conn:
            ticks = conn.execute(
                text("SELECT COUNT(*) FROM market_ticks WHERE season_id = :season_id"),
                {"season_id": self.season_id},
            ).scalar_one()
            quotes = conn.execute(
                text("SELECT COUNT(*) FROM market_tick_quotes WHERE season_id = :season_id"),
                {"season_id": self.season_id},
            ).scalar_one()

        self.assertEqual(ticks, expected_ticks)
        self.assertEqual(quotes, expected_quotes)


if __name__ == "__main__":
    unittest.main()

