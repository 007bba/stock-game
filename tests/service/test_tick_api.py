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

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.state import InMemoryState, Quote, Tick
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


class TestTickApi(unittest.TestCase):
    def setUp(self):
        os.environ["SUPABASE_USE_JWKS"] = "false"
        os.environ["SUPABASE_JWT_SECRET"] = "unit-test-secret"
        os.environ["SUPABASE_JWT_ISSUER"] = "https://supabase.test/auth/v1"

        self.snapshot = {
            "tickId": 101,
            "seasonId": 39,
            "gameDayNo": 1,
            "minuteOfDay": 3,
            "phase": "open_auction",
            "matchingMode": "batch_match",
            "isTradable": True,
            "isMatchingPoint": True,
            "nextTickId": 102,
            "nextTickAt": "2026-03-30T12:00:00+00:00",
            "quotes": [
                {
                    "tsCode": "000547.SZ",
                    "refPrice": 12.34,
                    "openPrice": 12.0,
                    "highPrice": 12.5,
                    "lowPrice": 11.8,
                    "closePrice": 12.34,
                    "vwapPrice": 12.2,
                    "volume": 123456,
                    "upperLimitPrice": 13.2,
                    "lowerLimitPrice": 10.8,
                    "isHalted": False,
                    "pctChange": 2.83,
                    "isLimitUp": False,
                    "isLimitDown": False,
                }
            ],
        }

        self.advance_result = {
            "season_id": 39,
            "advanced": True,
            "processed_ticks": 1,
            "matching_ticks": 1,
            "last_tick_id": 101,
            "tick": {
                "tickId": 101,
                "seasonId": 39,
                "gameDayNo": 1,
                "minuteOfDay": 3,
                "phase": "open_auction",
                "matchingMode": "batch_match",
                "isTradable": True,
                "isMatchingPoint": True,
            },
            "next_tick": {
                "tickId": 102,
                "seasonId": 39,
                "gameDayNo": 1,
                "minuteOfDay": 4,
                "phase": "am_continuous",
                "matchingMode": "accept_only",
                "isTradable": True,
                "isMatchingPoint": False,
            },
        }

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
            current_tick_snapshot_provider=lambda season_id: self.snapshot if season_id == 39 else None,
            advance_tick_provider=lambda season_id: self.advance_result if season_id == 39 else {"advanced": False},
        )

        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {make_test_token('tick-user')}"}

    def tearDown(self):
        os.environ.pop("SUPABASE_USE_JWKS", None)
        os.environ.pop("SUPABASE_JWT_SECRET", None)
        os.environ.pop("SUPABASE_JWT_ISSUER", None)

    def test_get_current_tick_snapshot_returns_payload(self):
        resp = self.client.get("/v1/seasons/39/ticks/current", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["tickId"], 101)
        self.assertEqual(len(body["quotes"]), 1)

    def test_get_current_tick_snapshot_returns_404_when_missing(self):
        resp = self.client.get("/v1/seasons/1/ticks/current", headers=self.headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "TICK_NOT_FOUND")

    def test_advance_tick_returns_provider_result(self):
        resp = self.client.post("/v1/seasons/39/ticks/advance", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["advanced"])


if __name__ == "__main__":
    unittest.main()
