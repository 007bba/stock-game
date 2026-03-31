from __future__ import annotations

import os
from collections.abc import Callable

from sqlalchemy import create_engine, text

from scripts.engine.state import Quote, Tick


class ReplayDataService:
    def __init__(self, database_url: str | None = None):
        if not database_url:
            database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for replay data service")

        self.engine = create_engine(database_url, future=True)

    @staticmethod
    def _to_tick(row) -> Tick:
        return Tick(
            id=int(row[0]),
            season_id=int(row[1]),
            game_day_no=int(row[2]),
            minute_of_day=int(row[3]),
            phase=str(row[4]),
            matching_mode=str(row[5]),
            is_tradable=bool(row[6]),
            is_matching_point=bool(row[7]),
        )

    def get_tick_by_id(self, season_id: int, tick_id: int) -> Tick | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, season_id, game_day_no, minute_of_day, phase, matching_mode, is_tradable, is_matching_point
                    FROM market_ticks
                    WHERE season_id = :season_id
                      AND id = :tick_id
                    LIMIT 1
                    """
                ),
                {"season_id": season_id, "tick_id": tick_id},
            ).fetchone()

        if row is None:
            return None
        return self._to_tick(row)

    def get_next_tick(self, season_id: int, after_tick_id: int = 0) -> Tick | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, season_id, game_day_no, minute_of_day, phase, matching_mode, is_tradable, is_matching_point
                    FROM market_ticks
                    WHERE season_id = :season_id
                      AND id > :after_tick_id
                    ORDER BY game_day_no, minute_of_day, id
                    LIMIT 1
                    """
                ),
                {"season_id": season_id, "after_tick_id": after_tick_id},
            ).fetchone()

        if row is None:
            return None
        return self._to_tick(row)

    def get_current_tick(self, season_id: int, current_tick_id: int | None = None) -> Tick | None:
        if current_tick_id is not None and current_tick_id > 0:
            current = self.get_tick_by_id(season_id=season_id, tick_id=current_tick_id)
            if current is not None:
                return current

        return self.get_next_tick(season_id=season_id, after_tick_id=0)

    def get_quote(self, season_id: int, tick_id: int, ts_code: str) -> Quote | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT ts_code, ref_price, upper_limit_price, lower_limit_price, is_halted
                    FROM market_tick_quotes
                    WHERE season_id = :season_id
                      AND tick_id = :tick_id
                      AND ts_code = :ts_code
                    LIMIT 1
                    """
                ),
                {"season_id": season_id, "tick_id": tick_id, "ts_code": ts_code},
            ).fetchone()

        if row is None:
            return None

        return Quote(
            ts_code=str(row[0]),
            ref_price=float(row[1]),
            upper_limit_price=float(row[2]),
            lower_limit_price=float(row[3]),
            is_halted=bool(row[4]),
        )

    def list_tick_quotes(self, season_id: int, tick_id: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                      ts_code,
                      ref_price,
                      open_price,
                      high_price,
                      low_price,
                      close_price,
                      vwap_price,
                      volume,
                      upper_limit_price,
                      lower_limit_price,
                                            is_halted,
                                            auction_imbalance_ratio,
                                            auction_hint_level
                    FROM market_tick_quotes
                    WHERE season_id = :season_id
                      AND tick_id = :tick_id
                    ORDER BY ts_code
                    """
                ),
                {"season_id": season_id, "tick_id": tick_id},
            ).fetchall()

        result: list[dict] = []
        for row in rows:
            open_price = float(row[2]) if row[2] is not None else None
            ref_price = float(row[1])
            pct_change = 0.0
            if open_price is not None and open_price > 0:
                pct_change = round((ref_price - open_price) / open_price * 100, 2)

            upper_limit_price = float(row[8])
            lower_limit_price = float(row[9])
            auction_imbalance_ratio = float(row[11]) if row[11] is not None else None
            auction_hint_level = int(row[12]) if row[12] is not None else 0
            result.append(
                {
                    "tsCode": str(row[0]),
                    "refPrice": ref_price,
                    "openPrice": open_price,
                    "highPrice": float(row[3]) if row[3] is not None else None,
                    "lowPrice": float(row[4]) if row[4] is not None else None,
                    "closePrice": float(row[5]) if row[5] is not None else None,
                    "vwapPrice": float(row[6]) if row[6] is not None else None,
                    "volume": int(row[7]),
                    "upperLimitPrice": upper_limit_price,
                    "lowerLimitPrice": lower_limit_price,
                    "isHalted": bool(row[10]),
                    "pctChange": pct_change,
                    "isLimitUp": ref_price >= upper_limit_price,
                    "isLimitDown": ref_price <= lower_limit_price,
                    "auctionImbalanceRatio": auction_imbalance_ratio,
                    "auctionHintLevel": auction_hint_level,
                }
            )

        return result


def build_current_tick_provider(
    replay_data: ReplayDataService,
    checkpoint_provider: Callable[[int], int] | None = None,
):
    def _provider(season_id: int) -> Tick:
        current_tick_id = checkpoint_provider(season_id) if checkpoint_provider is not None else 0
        tick = replay_data.get_current_tick(season_id=season_id, current_tick_id=current_tick_id)
        if tick is None:
            raise RuntimeError(f"no market_ticks found for season_id={season_id}")
        return tick

    return _provider


def build_current_quote_provider(
    replay_data: ReplayDataService,
    current_tick_provider,
):
    def _provider(season_id: int, ts_code: str) -> Quote:
        current_tick = current_tick_provider(season_id)
        quote = replay_data.get_quote(season_id=season_id, tick_id=current_tick.id, ts_code=ts_code)
        if quote is None:
            raise RuntimeError(
                f"no market_tick_quotes found for season_id={season_id}, tick_id={current_tick.id}, ts_code={ts_code}"
            )
        return quote

    return _provider
