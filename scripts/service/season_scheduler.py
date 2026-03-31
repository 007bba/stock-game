from __future__ import annotations

import json
import os
from typing import Callable

from sqlalchemy import create_engine, text

from scripts.engine.state import Quote, Tick


TickLoader = Callable[[int, int], list[Tick]]
QuoteLoader = Callable[[int, Tick], dict[str, Quote]]


class SeasonScheduler:
    def __init__(
        self,
        trading_service,
        tick_loader: TickLoader,
        quote_loader: QuoteLoader,
        checkpoint_file: str | None = None,
        event_bus=None,
    ):
        self.trading_service = trading_service
        self.tick_loader = tick_loader
        self.quote_loader = quote_loader
        self.checkpoint_file = checkpoint_file
        self.event_bus = event_bus
        self._checkpoints: dict[str, int] = {}
        self._load_checkpoints()

    def get_checkpoint(self, season_id: int) -> int:
        return int(self._checkpoints.get(str(season_id), 0))

    @staticmethod
    def _tick_to_dict(tick: Tick) -> dict:
        return {
            "tickId": tick.id,
            "seasonId": tick.season_id,
            "gameDayNo": tick.game_day_no,
            "minuteOfDay": tick.minute_of_day,
            "phase": tick.phase,
            "matchingMode": tick.matching_mode,
            "isTradable": tick.is_tradable,
            "isMatchingPoint": tick.is_matching_point,
        }

    def advance_tick(self, season_id: int) -> dict:
        key = str(season_id)
        last_tick_id = int(self._checkpoints.get(key, 0))

        ticks = self.tick_loader(season_id, last_tick_id)
        ticks = sorted(ticks, key=lambda item: (item.game_day_no, item.minute_of_day, item.id))

        if not ticks:
            return {
                "season_id": season_id,
                "advanced": False,
                "processed_ticks": 0,
                "matching_ticks": 0,
                "last_tick_id": last_tick_id,
                "tick": None,
                "next_tick": None,
            }

        tick = ticks[0]
        next_tick = ticks[1] if len(ticks) > 1 else None
        matching_ticks = 0

        if self.event_bus is not None:
            self.event_bus.emit_clock_tick(
                {
                    "seasonId": tick.season_id,
                    "gameDayNo": tick.game_day_no,
                    "minuteOfDay": tick.minute_of_day,
                    "phase": tick.phase,
                    "matchingMode": tick.matching_mode,
                    "tickId": tick.id,
                }
            )

        if tick.is_matching_point:
            quotes_by_code = self.quote_loader(season_id, tick)
            result = self.trading_service.process_tick(tick=tick, quotes_by_code=quotes_by_code)
            matching_ticks += 1

            if self.event_bus is not None:
                trade_ids = result.get("tradeIds", [])
                for trade_id in trade_ids:
                    self.event_bus.emit_trade_matched({"tradeId": trade_id, "tickId": tick.id})

        last_tick_id = max(last_tick_id, tick.id)
        self._checkpoints[key] = last_tick_id
        self._save_checkpoints()

        return {
            "season_id": season_id,
            "advanced": True,
            "processed_ticks": 1,
            "matching_ticks": matching_ticks,
            "last_tick_id": last_tick_id,
            "tick": self._tick_to_dict(tick),
            "next_tick": self._tick_to_dict(next_tick) if next_tick is not None else None,
        }

    def run_once(self, season_id: int) -> dict:
        processed_ticks = 0
        matching_ticks = 0
        result = self.advance_tick(season_id)
        while result["advanced"]:
            processed_ticks += int(result["processed_ticks"])
            matching_ticks += int(result["matching_ticks"])
            result = self.advance_tick(season_id)

        last_tick_id = self.get_checkpoint(season_id)

        return {
            "season_id": season_id,
            "processed_ticks": processed_ticks,
            "matching_ticks": matching_ticks,
            "last_tick_id": last_tick_id,
        }

    def _load_checkpoints(self):
        if not self.checkpoint_file:
            return
        if not os.path.exists(self.checkpoint_file):
            return

        with open(self.checkpoint_file, "r", encoding="utf-8") as file:
            payload = json.load(file)
            if isinstance(payload, dict):
                self._checkpoints = {str(key): int(value) for key, value in payload.items()}

    def _save_checkpoints(self):
        if not self.checkpoint_file:
            return

        parent_dir = os.path.dirname(self.checkpoint_file)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(self.checkpoint_file, "w", encoding="utf-8") as file:
            json.dump(self._checkpoints, file, ensure_ascii=False, indent=2)


def build_db_tick_loader(database_url: str | None = None) -> TickLoader:
    if not database_url:
        database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for DB tick loader")

    engine = create_engine(database_url, future=True)

    def load_ticks(season_id: int, after_tick_id: int) -> list[Tick]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, season_id, game_day_no, minute_of_day, phase, matching_mode, is_tradable, is_matching_point
                    FROM market_ticks
                    WHERE season_id = :season_id
                      AND id > :after_tick_id
                    ORDER BY game_day_no, minute_of_day, id
                    """
                ),
                {"season_id": season_id, "after_tick_id": after_tick_id},
            ).fetchall()

        out: list[Tick] = []
        for row in rows:
            out.append(
                Tick(
                    id=int(row[0]),
                    season_id=int(row[1]),
                    game_day_no=int(row[2]),
                    minute_of_day=int(row[3]),
                    phase=str(row[4]),
                    matching_mode=str(row[5]),
                    is_tradable=bool(row[6]),
                    is_matching_point=bool(row[7]),
                )
            )
        return out

    return load_ticks


def build_db_quote_loader(database_url: str | None = None) -> QuoteLoader:
    if not database_url:
        database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for DB quote loader")

    engine = create_engine(database_url, future=True)

    def load_quotes(season_id: int, tick: Tick) -> dict[str, Quote]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT ts_code, ref_price, upper_limit_price, lower_limit_price, is_halted
                    FROM market_tick_quotes
                    WHERE season_id = :season_id
                      AND tick_id = :tick_id
                    """
                ),
                {"season_id": season_id, "tick_id": tick.id},
            ).fetchall()

        out: dict[str, Quote] = {}
        for row in rows:
            quote = Quote(
                ts_code=str(row[0]),
                ref_price=float(row[1]),
                upper_limit_price=float(row[2]),
                lower_limit_price=float(row[3]),
                is_halted=bool(row[4]),
            )
            out[quote.ts_code] = quote
        return out

    return load_quotes
