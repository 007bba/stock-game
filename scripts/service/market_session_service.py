from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import psycopg2


TWOPLACES = Decimal('0.01')
FOURPLACES = Decimal('0.0001')


@dataclass
class MarketSessionError(Exception):
    code: str
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


class MarketSessionService:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @contextmanager
    def _conn(self):
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _to_decimal(value: Any, places: Decimal = TWOPLACES) -> Decimal:
        return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)

    @staticmethod
    def _build_login_name(user_id: str, email: str | None) -> str:
        if email:
            cleaned = email.strip().lower()
            if cleaned:
                return cleaned[:64]
        return f'user-{user_id}'[:64]

    @staticmethod
    def _build_display_name(user_id: str, email: str | None) -> str:
        if email:
            cleaned = email.strip()
            if cleaned:
                local_name = cleaned.split('@', 1)[0].strip()
                if local_name:
                    return local_name[:64]
        return f'player-{user_id[:8]}'[:64]

    def _ensure_user_exists(self, cur, user_id: str, email: str | None):
        cur.execute(
            """
            INSERT INTO users (id, login_name, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
              login_name = EXCLUDED.login_name,
              display_name = EXCLUDED.display_name
            """,
            (
                user_id,
                self._build_login_name(user_id=user_id, email=email),
                self._build_display_name(user_id=user_id, email=email),
            ),
        )

    def _require_session_row(self, cur, session_id: int, user_id: str, for_update: bool = False) -> dict[str, Any]:
        suffix = ' FOR UPDATE' if for_update else ''
        cur.execute(
            f"""
            SELECT id, user_id::text AS user_id, season_id, ts_code,
                   initial_cash, current_cash, current_step_no,
                   status::text AS status, started_at, finished_at, created_at
            FROM market_sessions
            WHERE id = %s AND user_id = %s
            LIMIT 1{suffix}
            """,
            (session_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            raise MarketSessionError(code='MARKET_SESSION_NOT_FOUND', message='market session not found', status_code=404)
        return {
            'id': int(row[0]),
            'userId': str(row[1]),
            'seasonId': int(row[2]),
            'tsCode': str(row[3]),
            'initialCash': float(row[4]),
            'currentCash': float(row[5]),
            'currentStepNo': int(row[6]),
            'status': str(row[7]),
            'startedAt': row[8].isoformat() if row[8] else None,
            'finishedAt': row[9].isoformat() if row[9] else None,
            'createdAt': row[10].isoformat() if row[10] else None,
        }

    def _require_position_row(self, cur, session_id: int, ts_code: str, for_update: bool = False) -> dict[str, Any]:
        suffix = ' FOR UPDATE' if for_update else ''
        cur.execute(
            f"""
            SELECT session_id, ts_code, qty_total, avg_cost, updated_at
            FROM market_session_positions
            WHERE session_id = %s AND ts_code = %s
            LIMIT 1{suffix}
            """,
            (session_id, ts_code),
        )
        row = cur.fetchone()
        if row is None:
            raise MarketSessionError(code='MARKET_POSITION_NOT_FOUND', message='market session position not found', status_code=404)
        return {
            'sessionId': int(row[0]),
            'tsCode': str(row[1]),
            'qtyTotal': int(row[2]),
            'avgCost': float(row[3]),
            'updatedAt': row[4].isoformat() if row[4] else None,
        }

    def _require_timeline_row(self, cur, season_id: int, ts_code: str, step_no: int) -> dict[str, Any]:
        cur.execute(
            """
            WITH timeline AS (
              SELECT
                ROW_NUMBER() OVER (ORDER BY mt.game_day_no, mt.minute_of_day, mt.id) AS step_no,
                mt.id AS tick_id,
                mt.game_day_no,
                mt.minute_of_day,
                mt.phase::text AS phase,
                COALESCE(mq.close_price, mq.ref_price) AS price,
                mq.volume
              FROM market_ticks mt
              JOIN market_tick_quotes mq ON mq.tick_id = mt.id
              WHERE mt.season_id = %s AND mq.ts_code = %s
              ORDER BY mt.game_day_no, mt.minute_of_day, mt.id
            )
            SELECT step_no, tick_id, game_day_no, minute_of_day, phase, price, volume
            FROM timeline
            WHERE step_no = %s
            LIMIT 1
            """,
            (season_id, ts_code, step_no),
        )
        row = cur.fetchone()
        if row is None:
            raise MarketSessionError(code='MARKET_STEP_NOT_FOUND', message='market session step not found', status_code=400)
        return {
            'stepNo': int(row[0]),
            'tickId': int(row[1]),
            'gameDayNo': int(row[2]),
            'minuteOfDay': int(row[3]),
            'phase': str(row[4]),
            'price': float(row[5]),
            'volume': int(row[6]),
        }

    def create_session(self, user_id: str, email: str | None, season_id: int, ts_code: str, initial_cash: float) -> dict[str, Any]:
        initial_cash_decimal = self._to_decimal(initial_cash)
        if initial_cash_decimal <= Decimal('0'):
            raise MarketSessionError(code='INITIAL_CASH_INVALID', message='initial cash must be greater than 0')

        with self._conn() as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1 FROM seasons WHERE id = %s LIMIT 1', (season_id,))
                    if cur.fetchone() is None:
                        raise MarketSessionError(code='SEASON_NOT_FOUND', message='season not found', status_code=404)

                    cur.execute(
                        """
                        SELECT 1
                        FROM season_universe
                        WHERE season_id = %s AND ts_code = %s AND is_active = TRUE
                        LIMIT 1
                        """,
                        (season_id, ts_code),
                    )
                    if cur.fetchone() is None:
                        raise MarketSessionError(code='TS_CODE_NOT_IN_SEASON', message='symbol is not active in season')

                    cur.execute(
                        """
                        SELECT 1
                        FROM market_tick_quotes mq
                        JOIN market_ticks mt ON mt.id = mq.tick_id
                        WHERE mt.season_id = %s AND mq.ts_code = %s
                        LIMIT 1
                        """,
                        (season_id, ts_code),
                    )
                    if cur.fetchone() is None:
                        raise MarketSessionError(code='TIMELINE_NOT_READY', message='timeline is not ready for this symbol', status_code=404)

                    self._ensure_user_exists(cur, user_id=user_id, email=email)
                    cur.execute(
                        """
                        INSERT INTO market_sessions (
                          user_id, season_id, ts_code, initial_cash, current_cash,
                          current_step_no, status, started_at
                        )
                        VALUES (%s, %s, %s, %s, %s, 1, CAST(%s AS market_session_status), now())
                        RETURNING id
                        """,
                        (user_id, season_id, ts_code, initial_cash_decimal, initial_cash_decimal, 'running'),
                    )
                    session_id = int(cur.fetchone()[0])
                    cur.execute(
                        """
                        INSERT INTO market_session_positions (session_id, ts_code, qty_total, avg_cost)
                        VALUES (%s, %s, 0, 0)
                        """,
                        (session_id, ts_code),
                    )

            return self.get_session(session_id=session_id, user_id=user_id)

    def get_session(self, session_id: int, user_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                session = self._require_session_row(cur, session_id=session_id, user_id=user_id)
                position = self._require_position_row(cur, session_id=session_id, ts_code=session['tsCode'])
                return {
                    **session,
                    'position': position,
                }

    def get_timeline(self, session_id: int, user_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                session = self._require_session_row(cur, session_id=session_id, user_id=user_id)
                cur.execute(
                    """
                    SELECT
                      ROW_NUMBER() OVER (ORDER BY mt.game_day_no, mt.minute_of_day, mt.id) AS step_no,
                      mt.id AS tick_id,
                      mt.game_day_no,
                      mt.minute_of_day,
                      mt.phase::text AS phase,
                      COALESCE(mq.close_price, mq.ref_price) AS price,
                      mq.volume
                    FROM market_ticks mt
                    JOIN market_tick_quotes mq ON mq.tick_id = mt.id
                    WHERE mt.season_id = %s AND mq.ts_code = %s
                    ORDER BY mt.game_day_no, mt.minute_of_day, mt.id
                    """,
                    (session['seasonId'], session['tsCode']),
                )
                rows = cur.fetchall()
                return {
                    'sessionId': session['id'],
                    'seasonId': session['seasonId'],
                    'tsCode': session['tsCode'],
                    'steps': [
                        {
                            'stepNo': int(row[0]),
                            'tickId': int(row[1]),
                            'gameDayNo': int(row[2]),
                            'minuteOfDay': int(row[3]),
                            'phase': str(row[4]),
                            'price': float(row[5]),
                            'volume': int(row[6]),
                        }
                        for row in rows
                    ],
                }

    def list_trades(self, session_id: int, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                self._require_session_row(cur, session_id=session_id, user_id=user_id)
                cur.execute(
                    """
                    SELECT
                      t.id,
                      t.session_id,
                      t.tick_id,
                      t.step_no,
                      t.ts_code,
                      t.side::text,
                      t.price,
                      t.quantity,
                      t.cash_after,
                      t.position_after,
                      t.avg_cost_basis,
                      t.created_at,
                      n.note,
                      n.tag
                    FROM market_session_trades t
                    LEFT JOIN market_session_trade_notes n ON n.trade_id = t.id
                    WHERE t.session_id = %s
                    ORDER BY t.id ASC
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
                return [self._trade_row_to_dto(row) for row in rows]

    def submit_trade(
        self,
        session_id: int,
        user_id: str,
        side: str,
        quantity: int,
        step_no: int,
        note: str | None,
        tag: str | None,
    ) -> dict[str, Any]:
        normalized_side = side.strip().lower()
        if normalized_side not in {'buy', 'sell'}:
            raise MarketSessionError(code='MARKET_TRADE_SIDE_INVALID', message='trade side must be buy or sell')
        if quantity <= 0 or quantity % 100 != 0:
            raise MarketSessionError(code='MARKET_TRADE_QTY_INVALID', message='quantity must be a positive lot of 100')
        if step_no <= 0:
            raise MarketSessionError(code='MARKET_STEP_INVALID', message='step_no must be greater than 0')

        with self._conn() as conn:
            with conn:
                with conn.cursor() as cur:
                    session = self._require_session_row(cur, session_id=session_id, user_id=user_id, for_update=True)
                    if session['status'] != 'running':
                        raise MarketSessionError(code='MARKET_SESSION_NOT_RUNNING', message='market session is not running')

                    position = self._require_position_row(cur, session_id=session_id, ts_code=session['tsCode'], for_update=True)
                    step = self._require_timeline_row(cur, season_id=session['seasonId'], ts_code=session['tsCode'], step_no=step_no)

                    price_decimal = self._to_decimal(step['price'])
                    current_cash_decimal = self._to_decimal(session['currentCash'])
                    current_avg_cost_decimal = self._to_decimal(position['avgCost'], FOURPLACES)
                    current_qty = int(position['qtyTotal'])
                    trade_value = (price_decimal * Decimal(quantity)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

                    if normalized_side == 'buy':
                        if current_cash_decimal < trade_value:
                            raise MarketSessionError(code='MARKET_INSUFFICIENT_CASH', message='insufficient cash for trade')
                        next_cash = current_cash_decimal - trade_value
                        next_qty = current_qty + quantity
                        next_avg_cost = ((current_avg_cost_decimal * Decimal(current_qty)) + trade_value) / Decimal(next_qty)
                        next_avg_cost = next_avg_cost.quantize(FOURPLACES, rounding=ROUND_HALF_UP)
                        avg_cost_basis = current_avg_cost_decimal
                    else:
                        if current_qty < quantity:
                            raise MarketSessionError(code='MARKET_INSUFFICIENT_POSITION', message='insufficient position for trade')
                        next_cash = current_cash_decimal + trade_value
                        next_qty = current_qty - quantity
                        next_avg_cost = current_avg_cost_decimal if next_qty > 0 else Decimal('0').quantize(FOURPLACES)
                        avg_cost_basis = current_avg_cost_decimal

                    cur.execute(
                        """
                        UPDATE market_sessions
                        SET current_cash = %s, current_step_no = %s
                        WHERE id = %s
                        """,
                        (next_cash, step_no, session_id),
                    )
                    cur.execute(
                        """
                        UPDATE market_session_positions
                        SET qty_total = %s, avg_cost = %s
                        WHERE session_id = %s AND ts_code = %s
                        """,
                        (next_qty, next_avg_cost, session_id, session['tsCode']),
                    )
                    cur.execute(
                        """
                        INSERT INTO market_session_trades (
                          session_id, tick_id, step_no, ts_code, side,
                          price, quantity, cash_after, position_after, avg_cost_basis
                        )
                        VALUES (%s, %s, %s, %s, CAST(%s AS market_trade_side), %s, %s, %s, %s, %s)
                        RETURNING id, session_id, tick_id, step_no, ts_code, side::text,
                                  price, quantity, cash_after, position_after, avg_cost_basis, created_at
                        """,
                        (
                            session_id,
                            step['tickId'],
                            step_no,
                            session['tsCode'],
                            normalized_side,
                            price_decimal,
                            quantity,
                            next_cash,
                            next_qty,
                            avg_cost_basis,
                        ),
                    )
                    trade_row = cur.fetchone()
                    trade_id = int(trade_row[0])

                    saved_note = None
                    saved_tag = None
                    if note is not None and note.strip():
                        saved_note = note.strip()
                        saved_tag = tag.strip() if tag and tag.strip() else None
                        cur.execute(
                            """
                            INSERT INTO market_session_trade_notes (trade_id, session_id, note, tag)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (trade_id, session_id, saved_note, saved_tag),
                        )

                    trade = self._trade_row_to_dto((*trade_row, saved_note, saved_tag))
                    session_response = {
                        **session,
                        'currentCash': float(next_cash),
                        'currentStepNo': step_no,
                        'position': {
                            'sessionId': session_id,
                            'tsCode': session['tsCode'],
                            'qtyTotal': int(next_qty),
                            'avgCost': float(next_avg_cost),
                            'updatedAt': None,
                        },
                    }

            return {
                'session': session_response,
                'trade': trade,
            }

    def finish_session(self, session_id: int, user_id: str, step_no: int) -> dict[str, Any]:
        if step_no <= 0:
            raise MarketSessionError(code='MARKET_STEP_INVALID', message='step_no must be greater than 0')

        with self._conn() as conn:
            with conn:
                with conn.cursor() as cur:
                    session = self._require_session_row(cur, session_id=session_id, user_id=user_id, for_update=True)
                    if session['status'] == 'finished':
                        result = self.get_result(session_id=session_id, user_id=user_id)
                        return result
                    if session['status'] != 'running':
                        raise MarketSessionError(code='MARKET_SESSION_NOT_RUNNING', message='market session is not running')

                    position = self._require_position_row(cur, session_id=session_id, ts_code=session['tsCode'], for_update=True)
                    step = self._require_timeline_row(cur, season_id=session['seasonId'], ts_code=session['tsCode'], step_no=step_no)
                    current_cash_decimal = self._to_decimal(session['currentCash'])
                    current_qty = int(position['qtyTotal'])
                    final_price_decimal = self._to_decimal(step['price'])
                    final_assets = (current_cash_decimal + final_price_decimal * Decimal(current_qty)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
                    initial_cash_decimal = self._to_decimal(session['initialCash'])
                    total_return_pct = Decimal('0')
                    if initial_cash_decimal > Decimal('0'):
                        total_return_pct = ((final_assets - initial_cash_decimal) / initial_cash_decimal * Decimal('100')).quantize(FOURPLACES, rounding=ROUND_HALF_UP)

                    cur.execute('SELECT COUNT(*) FROM market_session_trades WHERE session_id = %s', (session_id,))
                    trade_count = int(cur.fetchone()[0])
                    cur.execute(
                        """
                        SELECT COUNT(*), COALESCE(SUM(CASE WHEN price > avg_cost_basis THEN 1 ELSE 0 END), 0)
                        FROM market_session_trades
                        WHERE session_id = %s AND side = CAST('sell' AS market_trade_side)
                        """,
                        (session_id,),
                    )
                    sell_count, win_count = cur.fetchone()
                    win_rate = None
                    if int(sell_count) > 0:
                        win_rate = (Decimal(int(win_count)) / Decimal(int(sell_count)) * Decimal('100')).quantize(FOURPLACES, rounding=ROUND_HALF_UP)

                    cur.execute('SELECT COUNT(*) FROM market_session_trade_notes WHERE session_id = %s', (session_id,))
                    note_count = int(cur.fetchone()[0])
                    summary = self._build_summary(trade_count=trade_count, note_count=note_count, position_qty=current_qty)

                    cur.execute(
                        """
                        UPDATE market_sessions
                        SET status = CAST(%s AS market_session_status), current_step_no = %s, finished_at = now()
                        WHERE id = %s
                        """,
                        ('finished', step_no, session_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO market_session_results (
                          session_id, final_step_no, final_price, final_cash, final_position_qty,
                          final_assets, total_return_pct, trade_count, win_rate, summary
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET
                          final_step_no = EXCLUDED.final_step_no,
                          final_price = EXCLUDED.final_price,
                          final_cash = EXCLUDED.final_cash,
                          final_position_qty = EXCLUDED.final_position_qty,
                          final_assets = EXCLUDED.final_assets,
                          total_return_pct = EXCLUDED.total_return_pct,
                          trade_count = EXCLUDED.trade_count,
                          win_rate = EXCLUDED.win_rate,
                          summary = EXCLUDED.summary
                        """,
                        (
                            session_id,
                            step_no,
                            final_price_decimal,
                            current_cash_decimal,
                            current_qty,
                            final_assets,
                            total_return_pct,
                            trade_count,
                            win_rate,
                            summary,
                        ),
                    )

            return {
                'sessionId': session_id,
                'seasonId': session['seasonId'],
                'tsCode': session['tsCode'],
                'finalStepNo': step_no,
                'finalPrice': float(final_price_decimal),
                'finalCash': float(current_cash_decimal),
                'finalPositionQty': current_qty,
                'finalAssets': float(final_assets),
                'totalReturnPct': float(total_return_pct),
                'tradeCount': trade_count,
                'winRate': float(win_rate) if win_rate is not None else None,
                'summary': summary,
                'createdAt': None,
            }

    def get_result(self, session_id: int, user_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                session = self._require_session_row(cur, session_id=session_id, user_id=user_id)
                cur.execute(
                    """
                    SELECT session_id, final_step_no, final_price, final_cash, final_position_qty,
                           final_assets, total_return_pct, trade_count, win_rate, summary, created_at
                    FROM market_session_results
                    WHERE session_id = %s
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise MarketSessionError(code='MARKET_SESSION_RESULT_NOT_FOUND', message='market session result not found', status_code=404)
                return {
                    'sessionId': int(row[0]),
                    'seasonId': session['seasonId'],
                    'tsCode': session['tsCode'],
                    'finalStepNo': int(row[1]),
                    'finalPrice': float(row[2]),
                    'finalCash': float(row[3]),
                    'finalPositionQty': int(row[4]),
                    'finalAssets': float(row[5]),
                    'totalReturnPct': float(row[6]),
                    'tradeCount': int(row[7]),
                    'winRate': float(row[8]) if row[8] is not None else None,
                    'summary': str(row[9]) if row[9] is not None else '',
                    'createdAt': row[10].isoformat() if row[10] else None,
                }

    @staticmethod
    def _build_summary(trade_count: int, note_count: int, position_qty: int) -> str:
        if trade_count == 0:
            return '本次训练没有成交，先把回放与决策记录跑通。'
        if note_count < trade_count:
            return '有成交但理由记录不完整，下一步先补齐每笔交易的理由。'
        if trade_count > 12:
            return '交易次数偏多，先检查是否存在频繁试错或追单。'
        if position_qty > 0:
            return '训练结束时仍有持仓，复盘时重点检查持有依据是否充分。'
        return '训练闭环已跑通，可以继续补规则评分和结果分析。'

    @staticmethod
    def _trade_row_to_dto(row) -> dict[str, Any]:
        return {
            'tradeId': int(row[0]),
            'sessionId': int(row[1]),
            'tickId': int(row[2]),
            'stepNo': int(row[3]),
            'tsCode': str(row[4]),
            'side': str(row[5]),
            'price': float(row[6]),
            'quantity': int(row[7]),
            'cashAfter': float(row[8]),
            'positionAfter': int(row[9]),
            'avgCostBasis': float(row[10]),
            'createdAt': row[11].isoformat() if row[11] else None,
            'note': str(row[12]) if row[12] is not None else None,
            'tag': str(row[13]) if row[13] is not None else None,
        }
