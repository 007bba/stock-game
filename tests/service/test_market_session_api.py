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
from scripts.service.market_session_service import MarketSessionError
from scripts.service.trading_service import TradingService


def _encode_segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('utf-8').rstrip('=')


def make_test_token(
    user_id: str,
    *,
    audience: str = 'authenticated',
    issuer: str = 'https://supabase.test/auth/v1',
    exp_offset_seconds: int = 3600,
) -> str:
    secret = os.environ['SUPABASE_JWT_SECRET']
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'sub': user_id,
        'email': f'{user_id}@stock-game.local',
        'aud': audience,
        'iss': issuer,
        'exp': int(time.time()) + exp_offset_seconds,
    }

    encoded_header = _encode_segment(header)
    encoded_payload = _encode_segment(payload)
    signing_input = f'{encoded_header}.{encoded_payload}'.encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
    return f'{encoded_header}.{encoded_payload}.{encoded_signature}'


class FakeMarketSessionService:
    def __init__(self):
        self.next_session_id = 1
        self.sessions: dict[int, dict] = {}
        self.trades: dict[int, list[dict]] = {}
        self.results: dict[int, dict] = {}
        self.timeline_steps = [
            {'stepNo': 1, 'tickId': 1001, 'gameDayNo': 1, 'minuteOfDay': 1, 'phase': 'open_auction', 'price': 10.0, 'volume': 0},
            {'stepNo': 2, 'tickId': 1002, 'gameDayNo': 1, 'minuteOfDay': 2, 'phase': 'am_continuous', 'price': 10.5, 'volume': 1000},
            {'stepNo': 3, 'tickId': 1003, 'gameDayNo': 1, 'minuteOfDay': 3, 'phase': 'am_continuous', 'price': 11.0, 'volume': 1200},
        ]

    def create_session(self, user_id: str, email: str | None, season_id: int, ts_code: str, initial_cash: float) -> dict:
        _ = email
        session_id = self.next_session_id
        self.next_session_id += 1
        session = {
            'id': session_id,
            'userId': user_id,
            'seasonId': season_id,
            'tsCode': ts_code,
            'initialCash': float(initial_cash),
            'currentCash': float(initial_cash),
            'currentStepNo': 1,
            'status': 'running',
            'startedAt': '2026-03-31T12:00:00+00:00',
            'finishedAt': None,
            'createdAt': '2026-03-31T12:00:00+00:00',
            'position': {
                'sessionId': session_id,
                'tsCode': ts_code,
                'qtyTotal': 0,
                'avgCost': 0.0,
                'updatedAt': '2026-03-31T12:00:00+00:00',
            },
        }
        self.sessions[session_id] = session
        self.trades[session_id] = []
        return session

    def _require_session(self, session_id: int, user_id: str) -> dict:
        session = self.sessions.get(session_id)
        if session is None or session['userId'] != user_id:
            raise MarketSessionError(code='MARKET_SESSION_NOT_FOUND', message='market session not found', status_code=404)
        return session

    def get_session(self, session_id: int, user_id: str) -> dict:
        return self._require_session(session_id, user_id)

    def get_timeline(self, session_id: int, user_id: str) -> dict:
        session = self._require_session(session_id, user_id)
        return {
            'sessionId': session_id,
            'seasonId': session['seasonId'],
            'tsCode': session['tsCode'],
            'steps': self.timeline_steps,
        }

    def list_trades(self, session_id: int, user_id: str) -> list[dict]:
        self._require_session(session_id, user_id)
        return self.trades[session_id]

    def submit_trade(self, session_id: int, user_id: str, side: str, quantity: int, step_no: int, note: str | None, tag: str | None) -> dict:
        session = self._require_session(session_id, user_id)
        if quantity <= 0 or quantity % 100 != 0:
            raise MarketSessionError(code='MARKET_TRADE_QTY_INVALID', message='quantity must be a positive lot of 100')
        if step_no < 1 or step_no > len(self.timeline_steps):
            raise MarketSessionError(code='MARKET_STEP_NOT_FOUND', message='market session step not found')
        if session['status'] != 'running':
            raise MarketSessionError(code='MARKET_SESSION_NOT_RUNNING', message='market session is not running')

        step = self.timeline_steps[step_no - 1]
        price = float(step['price'])
        qty = session['position']['qtyTotal']
        avg_cost = session['position']['avgCost']
        if side == 'buy':
            cost = price * quantity
            if session['currentCash'] < cost:
                raise MarketSessionError(code='MARKET_INSUFFICIENT_CASH', message='insufficient cash for trade')
            session['currentCash'] -= cost
            next_qty = qty + quantity
            session['position']['avgCost'] = ((avg_cost * qty) + cost) / next_qty
            session['position']['qtyTotal'] = next_qty
            avg_cost_basis = avg_cost
        else:
            if qty < quantity:
                raise MarketSessionError(code='MARKET_INSUFFICIENT_POSITION', message='insufficient position for trade')
            session['currentCash'] += price * quantity
            session['position']['qtyTotal'] = qty - quantity
            if session['position']['qtyTotal'] == 0:
                session['position']['avgCost'] = 0.0
            avg_cost_basis = avg_cost

        session['currentStepNo'] = step_no
        trade = {
            'tradeId': len(self.trades[session_id]) + 1,
            'sessionId': session_id,
            'tickId': step['tickId'],
            'stepNo': step_no,
            'tsCode': session['tsCode'],
            'side': side,
            'price': price,
            'quantity': quantity,
            'cashAfter': session['currentCash'],
            'positionAfter': session['position']['qtyTotal'],
            'avgCostBasis': avg_cost_basis,
            'createdAt': '2026-03-31T12:05:00+00:00',
            'note': note,
            'tag': tag,
        }
        self.trades[session_id].append(trade)
        return {'session': session, 'trade': trade}

    def finish_session(self, session_id: int, user_id: str, step_no: int) -> dict:
        session = self._require_session(session_id, user_id)
        step = self.timeline_steps[step_no - 1]
        final_assets = session['currentCash'] + session['position']['qtyTotal'] * float(step['price'])
        result = {
            'sessionId': session_id,
            'seasonId': session['seasonId'],
            'tsCode': session['tsCode'],
            'finalStepNo': step_no,
            'finalPrice': float(step['price']),
            'finalCash': session['currentCash'],
            'finalPositionQty': session['position']['qtyTotal'],
            'finalAssets': final_assets,
            'totalReturnPct': ((final_assets - session['initialCash']) / session['initialCash']) * 100,
            'tradeCount': len(self.trades[session_id]),
            'winRate': None,
            'summary': '训练闭环已跑通，可以继续补规则评分和结果分析。',
            'createdAt': '2026-03-31T12:10:00+00:00',
        }
        session['status'] = 'finished'
        session['finishedAt'] = '2026-03-31T12:10:00+00:00'
        self.results[session_id] = result
        return result

    def get_result(self, session_id: int, user_id: str) -> dict:
        self._require_session(session_id, user_id)
        result = self.results.get(session_id)
        if result is None:
            raise MarketSessionError(code='MARKET_SESSION_RESULT_NOT_FOUND', message='market session result not found', status_code=404)
        return result


class TestMarketSessionApi(unittest.TestCase):
    def setUp(self):
        os.environ['SUPABASE_USE_JWKS'] = 'false'
        os.environ['SUPABASE_JWT_SECRET'] = 'unit-test-secret'
        os.environ['SUPABASE_JWT_ISSUER'] = 'https://supabase.test/auth/v1'

        self.market_session_service = FakeMarketSessionService()
        app = create_app(
            trading_service=TradingService(InMemoryState()),
            tick_provider=lambda season_id: Tick(
                id=1,
                season_id=season_id,
                game_day_no=1,
                minute_of_day=1,
                phase='am_continuous',
                matching_mode='accept_only',
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
            market_session_service=self.market_session_service,
        )
        self.client = TestClient(app)
        self.headers = {'Authorization': f"Bearer {make_test_token('market-user')}"}

    def tearDown(self):
        os.environ.pop('SUPABASE_USE_JWKS', None)
        os.environ.pop('SUPABASE_JWT_SECRET', None)
        os.environ.pop('SUPABASE_JWT_ISSUER', None)

    def test_create_market_session_requires_auth(self):
        resp = self.client.post('/v2/market-sessions', json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000})
        self.assertEqual(resp.status_code, 401)

    def test_create_market_session_returns_session_payload(self):
        resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000},
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['seasonId'], 43)
        self.assertEqual(body['tsCode'], '000547.SZ')
        self.assertEqual(body['position']['qtyTotal'], 0)

    def test_get_timeline_returns_steps(self):
        create_resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000},
        )
        session_id = create_resp.json()['id']

        timeline_resp = self.client.get(f'/v2/market-sessions/{session_id}/timeline', headers=self.headers)
        self.assertEqual(timeline_resp.status_code, 200)
        self.assertEqual(len(timeline_resp.json()['steps']), 3)

    def test_submit_trade_records_note_and_updates_session(self):
        create_resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000},
        )
        session_id = create_resp.json()['id']

        trade_resp = self.client.post(
            f'/v2/market-sessions/{session_id}/trades',
            headers=self.headers,
            json={'side': 'buy', 'quantity': 100, 'stepNo': 2, 'note': '突破后试错', 'tag': '追涨'},
        )
        self.assertEqual(trade_resp.status_code, 201)
        body = trade_resp.json()
        self.assertEqual(body['trade']['note'], '突破后试错')
        self.assertEqual(body['session']['position']['qtyTotal'], 100)

        list_resp = self.client.get(f'/v2/market-sessions/{session_id}/trades', headers=self.headers)
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()), 1)

    def test_submit_trade_rejects_invalid_quantity(self):
        create_resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000},
        )
        session_id = create_resp.json()['id']

        trade_resp = self.client.post(
            f'/v2/market-sessions/{session_id}/trades',
            headers=self.headers,
            json={'side': 'buy', 'quantity': 10, 'stepNo': 2},
        )
        self.assertEqual(trade_resp.status_code, 400)
        self.assertEqual(trade_resp.json()['code'], 'MARKET_TRADE_QTY_INVALID')

    def test_submit_trade_rejects_insufficient_cash(self):
        create_resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 100},
        )
        session_id = create_resp.json()['id']

        trade_resp = self.client.post(
            f'/v2/market-sessions/{session_id}/trades',
            headers=self.headers,
            json={'side': 'buy', 'quantity': 100, 'stepNo': 3},
        )
        self.assertEqual(trade_resp.status_code, 400)
        self.assertEqual(trade_resp.json()['code'], 'MARKET_INSUFFICIENT_CASH')

    def test_finish_and_get_result(self):
        create_resp = self.client.post(
            '/v2/market-sessions',
            headers=self.headers,
            json={'seasonId': 43, 'tsCode': '000547.SZ', 'initialCash': 1000000},
        )
        session_id = create_resp.json()['id']
        self.client.post(
            f'/v2/market-sessions/{session_id}/trades',
            headers=self.headers,
            json={'side': 'buy', 'quantity': 100, 'stepNo': 2, 'note': '试错单'},
        )

        finish_resp = self.client.post(
            f'/v2/market-sessions/{session_id}/finish',
            headers=self.headers,
            json={'stepNo': 3},
        )
        self.assertEqual(finish_resp.status_code, 200)
        self.assertEqual(finish_resp.json()['tradeCount'], 1)

        result_resp = self.client.get(f'/v2/market-sessions/{session_id}/result', headers=self.headers)
        self.assertEqual(result_resp.status_code, 200)
        self.assertEqual(result_resp.json()['finalStepNo'], 3)

    def test_missing_market_session_returns_404(self):
        resp = self.client.get('/v2/market-sessions/999', headers=self.headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['code'], 'MARKET_SESSION_NOT_FOUND')


if __name__ == '__main__':
    unittest.main()
