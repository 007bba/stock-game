import pathlib
import sys
import unittest
from unittest import mock

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
ETL_PATH = ROOT / "scripts" / "etl"
if str(ETL_PATH) not in sys.path:
    sys.path.insert(0, str(ETL_PATH))

import tushare_pipeline as tp


class TestTusharePipeline(unittest.TestCase):
    def test_split_even_windows_uneven(self):
        df = pd.DataFrame({"x": list(range(10))})
        windows = tp.split_even_windows(df, 3)
        self.assertEqual([len(w) for w in windows], [4, 3, 3])

    def test_synthesize_minute_from_daily(self):
        daily = pd.DataFrame(
            [
                {
                    "trade_date": "2026-01-06",
                    "open": 10.0,
                    "high": 10.8,
                    "low": 9.7,
                    "close": 10.5,
                    "vol": 240000,
                    "amount": 2500000,
                }
            ]
        )
        minute_df = tp._synthesize_minute_from_daily(tp._normalize_daily_df(daily))
        self.assertEqual(len(minute_df), 240)
        self.assertGreaterEqual(float(minute_df["high"].max()), 10.8)
        self.assertLessEqual(float(minute_df["low"].min()), 9.7)

    def test_build_quote_timeline(self):
        am_times = pd.date_range("2026-01-06 09:30:00+08:00", periods=120, freq="min")
        pm_times = pd.date_range("2026-01-06 13:00:00+08:00", periods=120, freq="min")
        rows = []
        price = 10.0
        for ts in list(am_times) + list(pm_times):
            close_p = price * 1.0005
            rows.append(
                {
                    "trade_time": ts.tz_convert("UTC"),
                    "open_price": price,
                    "high_price": max(price, close_p),
                    "low_price": min(price, close_p),
                    "close_price": close_p,
                    "vol": 1000,
                    "amount": 1000 * ((price + close_p) / 2),
                }
            )
            price = close_p
        day_df = pd.DataFrame(rows)

        timeline = tp.build_quote_timeline(day_df=day_df, prev_close=9.8, halted=False)
        self.assertEqual(len(timeline), 60)
        for minute in range(1, 61):
            quote = timeline[minute]
            self.assertGreater(quote["upper_limit_price"], quote["lower_limit_price"])
            self.assertGreaterEqual(quote["ref_price"], quote["lower_limit_price"])
            self.assertLessEqual(quote["ref_price"], quote["upper_limit_price"])
            if minute not in tp.MATCHING_MINUTES:
                self.assertEqual(quote["volume"], 0)

    def test_normalize_adj_factor_df(self):
        raw = pd.DataFrame(
            [
                {"trade_date": "20260105", "adj_factor": "1.01"},
                {"trade_date": "20260106", "adj_factor": "1.02"},
                {"trade_date": "20260106", "adj_factor": "1.02"},
                {"trade_date": "20260107", "adj_factor": "1.03"},
            ]
        )
        out = tp.normalize_adj_factor_df(raw, "2026-01-06", "2026-01-07")
        self.assertEqual(len(out), 2)
        self.assertEqual(str(out.iloc[0]["trade_date"]), "2026-01-06")
        self.assertAlmostEqual(float(out.iloc[1]["adj_factor"]), 1.03, places=6)

    def test_call_tushare_with_retry(self):
        state = {"n": 0}

        def flaky_api(**kwargs):
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("抱歉，您每分钟最多访问该接口2次")
            return {"ok": True, "kwargs": kwargs}

        with mock.patch("tushare_pipeline.pytime.sleep", return_value=None):
            result = tp.call_tushare_with_retry("test_api", flaky_api, retries=3, base_sleep_seconds=1, foo=1)

        self.assertTrue(result["ok"])
        self.assertEqual(state["n"], 3)

    def test_call_tushare_with_retry_non_retryable(self):
        def bad_api(**kwargs):
            raise RuntimeError("schema mismatch")

        with mock.patch("tushare_pipeline.pytime.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                tp.call_tushare_with_retry("bad_api", bad_api, retries=3, base_sleep_seconds=1)


if __name__ == "__main__":
    unittest.main()

