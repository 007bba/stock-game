"""Seed deterministic replay ticks/quotes for a season.

This script generates a complete replay scaffold directly in DB so development
can continue without external data providers.

Usage:
  python scripts/etl/seed_replay_fixture.py --season-id 39 --overwrite

Optional:
  python scripts/etl/seed_replay_fixture.py --season-id 39 --game-days 10 --seed 20260330 --overwrite
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

MATCHING_MINUTES = {3, 8, 13, 18, 23, 29, 36, 41, 46, 51, 57, 60}
AUCTION_MINUTES = {1, 2, 3, 58, 59, 60}


@dataclass
class Config:
    season_id: int
    game_days: int | None
    seed: int
    start_date: date
    overwrite: bool


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Seed deterministic replay fixture for a season")
    parser.add_argument("--season-id", type=int, required=True)
    parser.add_argument("--game-days", type=int, default=None)
    parser.add_argument("--seed", type=int, default=20260330)
    parser.add_argument("--start-date", type=str, default="2025-12-01")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    return Config(
        season_id=args.season_id,
        game_days=args.game_days,
        seed=args.seed,
        start_date=date.fromisoformat(args.start_date),
        overwrite=bool(args.overwrite),
    )


def round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_hint_level(ref_price: float, prev_close: float, imbalance_ratio: float) -> int:
    if prev_close <= 0:
        return 0
    gap = abs((ref_price - prev_close) / prev_close)
    abs_imbalance = abs(imbalance_ratio)
    if abs_imbalance >= 0.95 or gap >= 0.03:
        return 3
    if abs_imbalance >= 0.85 or gap >= 0.015:
        return 2
    return 0


def minute_meta(minute: int) -> tuple[str, str, bool, bool]:
    if 1 <= minute <= 3:
        return "open_auction", ("accept_only" if minute < 3 else "open_call_auction"), True, minute == 3
    if 4 <= minute <= 29:
        return "am_continuous", ("batch_match" if minute in MATCHING_MINUTES else "accept_only"), True, minute in MATCHING_MINUTES
    if 30 <= minute <= 31:
        return "lunch_break", "frozen", False, False
    if 32 <= minute <= 57:
        return "pm_continuous", ("batch_match" if minute in MATCHING_MINUTES else "accept_only"), True, minute in MATCHING_MINUTES
    return "close_auction", ("accept_only" if minute < 60 else "close_call_auction"), True, minute == 60


def digest_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return create_engine(database_url, future=True)


def resolve_game_days(conn, season_id: int, requested: int | None) -> int:
    if requested is not None:
        if requested <= 0:
            raise ValueError("--game-days must be > 0")
        return requested

    row = conn.execute(
        text("SELECT total_game_days FROM seasons WHERE id = :season_id"),
        {"season_id": season_id},
    ).fetchone()
    if row is None:
        raise RuntimeError(f"season_id={season_id} not found")
    value = int(row[0])
    if value <= 0:
        raise RuntimeError(f"season_id={season_id} has invalid total_game_days={value}")
    return value


def load_universe(conn, season_id: int) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT ts_code
            FROM season_universe
            WHERE season_id = :season_id
              AND is_active = TRUE
            ORDER BY rank_in_theme, ts_code
            """
        ),
        {"season_id": season_id},
    ).fetchall()
    return [str(row[0]) for row in rows]


def build_tick_ids(conn, season_id: int, game_day_no: int, day_anchor: datetime) -> list[int]:
    tick_ids: list[int] = []
    for minute in range(1, 61):
        phase, mode, tradable, matching = minute_meta(minute)
        row = conn.execute(
            text(
                """
                INSERT INTO market_ticks (
                  season_id, game_day_no, minute_of_day,
                  phase, matching_mode, is_tradable, is_matching_point, scheduled_at
                ) VALUES (
                  :season_id, :game_day_no, :minute_of_day,
                  CAST(:phase AS session_phase), CAST(:matching_mode AS matching_mode),
                  :is_tradable, :is_matching_point, :scheduled_at
                )
                ON CONFLICT (season_id, game_day_no, minute_of_day)
                DO UPDATE SET
                  phase = EXCLUDED.phase,
                  matching_mode = EXCLUDED.matching_mode,
                  is_tradable = EXCLUDED.is_tradable,
                  is_matching_point = EXCLUDED.is_matching_point,
                  scheduled_at = EXCLUDED.scheduled_at
                RETURNING id
                """
            ),
            {
                "season_id": season_id,
                "game_day_no": game_day_no,
                "minute_of_day": minute,
                "phase": phase,
                "matching_mode": mode,
                "is_tradable": tradable,
                "is_matching_point": matching,
                "scheduled_at": (day_anchor + timedelta(minutes=minute - 1)).astimezone(ZoneInfo("UTC")),
            },
        ).fetchone()
        tick_ids.append(int(row[0]))
    return tick_ids


def seed_symbol_day_rows(
    ts_code: str,
    season_id: int,
    game_day_no: int,
    tick_ids: list[int],
    prev_close: float,
    global_seed: int,
) -> tuple[list[dict], float]:
    symbol_seed = digest_int(f"{global_seed}:{ts_code}")
    day_seed = digest_int(f"{global_seed}:{ts_code}:{game_day_no}")
    rng = random.Random(day_seed)

    upper_limit = round_price(prev_close * 1.1)
    lower_limit = round_price(prev_close * 0.9)

    day_open = clamp(prev_close * (1 + rng.uniform(-0.025, 0.035)), lower_limit * 1.001, upper_limit * 0.999)
    day_close_target = clamp(day_open * (1 + rng.uniform(-0.03, 0.05)), lower_limit * 1.001, upper_limit * 0.999)

    phase_shift = rng.uniform(0, 2 * math.pi)
    volatility = max(prev_close * rng.uniform(0.0015, 0.0075), 0.002)
    base_volume = 800 + (symbol_seed % 6200)

    rows: list[dict] = []
    last_close = day_open
    for minute in range(1, 61):
        progress = (minute - 1) / 59.0
        trend = day_open + (day_close_target - day_open) * progress
        wave = math.sin(progress * 2 * math.pi + phase_shift) * volatility
        close_price = clamp(trend + wave, lower_limit * 1.001, upper_limit * 0.999)

        open_price = last_close if minute > 1 else day_open
        high_price = max(open_price, close_price)
        low_price = min(open_price, close_price)
        wiggle = volatility * (0.1 + 0.3 * rng.random())
        high_price = clamp(high_price + wiggle, lower_limit * 1.001, upper_limit * 0.999)
        low_price = clamp(low_price - wiggle, lower_limit * 1.001, upper_limit * 0.999)
        if low_price > high_price:
            low_price, high_price = high_price, low_price

        ref_price = close_price
        vwap_price = (open_price + high_price + low_price + close_price) / 4.0

        volume = 0
        if minute in MATCHING_MINUTES:
            volume = int(
                base_volume
                * (0.8 + 0.4 * rng.random())
                * (1 + abs(close_price - open_price) / max(prev_close, 0.01) * 25)
            )
            volume = max(volume, 100)

        auction_imbalance_ratio = 0.0
        auction_hint_level = 0
        if minute in AUCTION_MINUTES:
            directional_bias = ((day_close_target - prev_close) / max(prev_close, 0.01)) * 12.0
            auction_imbalance_ratio = clamp(directional_bias + rng.uniform(-0.15, 0.15), -0.99, 0.99)
            auction_hint_level = compute_hint_level(ref_price, prev_close, auction_imbalance_ratio)

        rows.append(
            {
                "tick_id": tick_ids[minute - 1],
                "season_id": season_id,
                "ts_code": ts_code,
                "ref_price": round_price(ref_price),
                "open_price": round_price(open_price),
                "high_price": round_price(high_price),
                "low_price": round_price(low_price),
                "close_price": round_price(close_price),
                "vwap_price": round_price(vwap_price),
                "volume": int(volume),
                "volume_factor": 1.0,
                "upper_limit_price": upper_limit,
                "lower_limit_price": lower_limit,
                "is_halted": False,
                "auction_imbalance_ratio": round(float(auction_imbalance_ratio), 6),
                "auction_hint_level": int(auction_hint_level),
            }
        )
        last_close = close_price

    return rows, round_price(last_close)


def validate_seeded_data(conn, season_id: int, universe_size: int, game_days: int):
    tick_count = int(
        conn.execute(
            text("SELECT COUNT(*) FROM market_ticks WHERE season_id = :season_id"),
            {"season_id": season_id},
        ).scalar_one()
    )
    quote_count = int(
        conn.execute(
            text("SELECT COUNT(*) FROM market_tick_quotes WHERE season_id = :season_id"),
            {"season_id": season_id},
        ).scalar_one()
    )
    row = conn.execute(
        text(
            """
            SELECT MIN(c), MAX(c)
            FROM (
              SELECT tick_id, COUNT(*)::INT AS c
              FROM market_tick_quotes
              WHERE season_id = :season_id
              GROUP BY tick_id
            ) t
            """
        ),
        {"season_id": season_id},
    ).fetchone()
    min_per_tick = int(row[0] or 0)
    max_per_tick = int(row[1] or 0)

    non_matching_positive_volume = int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM market_tick_quotes mq
                JOIN market_ticks mt ON mt.id = mq.tick_id
                WHERE mq.season_id = :season_id
                  AND mt.minute_of_day NOT IN (3,8,13,18,23,29,36,41,46,51,57,60)
                  AND mq.volume > 0
                """
            ),
            {"season_id": season_id},
        ).scalar_one()
    )

    expected_ticks = game_days * 60
    expected_quotes = expected_ticks * universe_size

    if tick_count != expected_ticks:
        raise RuntimeError(f"tick_count={tick_count}, expected={expected_ticks}")
    if quote_count != expected_quotes:
        raise RuntimeError(f"quote_count={quote_count}, expected={expected_quotes}")
    if min_per_tick != universe_size or max_per_tick != universe_size:
        raise RuntimeError(
            f"quote_per_tick mismatch: min={min_per_tick}, max={max_per_tick}, expected={universe_size}"
        )
    if non_matching_positive_volume > 0:
        raise RuntimeError(
            f"non_matching_positive_volume={non_matching_positive_volume}, expected=0"
        )

    print(
        f"seed verification ok: ticks={tick_count}, quotes={quote_count}, "
        f"quote_per_tick={min_per_tick}, universe={universe_size}"
    )


def run(cfg: Config):
    engine = get_engine()
    with engine.begin() as conn:
        universe = load_universe(conn, cfg.season_id)
        if not universe:
            raise RuntimeError(f"season_id={cfg.season_id} has empty active universe")

        game_days = resolve_game_days(conn, cfg.season_id, cfg.game_days)

        if cfg.overwrite:
            conn.execute(
                text("DELETE FROM market_tick_quotes WHERE season_id = :season_id"),
                {"season_id": cfg.season_id},
            )
            conn.execute(
                text("DELETE FROM market_ticks WHERE season_id = :season_id"),
                {"season_id": cfg.season_id},
            )

        prev_close_by_code: dict[str, float] = {}
        for ts_code in universe:
            base = 6.0 + (digest_int(f"{cfg.seed}:{ts_code}:base") % 2200) / 100.0
            prev_close_by_code[ts_code] = round_price(base)

        insert_quotes_sql = text(
            """
            INSERT INTO market_tick_quotes (
              tick_id, season_id, ts_code,
              ref_price, open_price, high_price, low_price, close_price, vwap_price,
              volume, volume_factor,
              upper_limit_price, lower_limit_price,
              is_halted, auction_imbalance_ratio, auction_hint_level
            ) VALUES (
              :tick_id, :season_id, :ts_code,
              :ref_price, :open_price, :high_price, :low_price, :close_price, :vwap_price,
              :volume, :volume_factor,
              :upper_limit_price, :lower_limit_price,
              :is_halted, :auction_imbalance_ratio, :auction_hint_level
            )
            ON CONFLICT (tick_id, ts_code)
            DO UPDATE SET
              ref_price = EXCLUDED.ref_price,
              open_price = EXCLUDED.open_price,
              high_price = EXCLUDED.high_price,
              low_price = EXCLUDED.low_price,
              close_price = EXCLUDED.close_price,
              vwap_price = EXCLUDED.vwap_price,
              volume = EXCLUDED.volume,
              volume_factor = EXCLUDED.volume_factor,
              upper_limit_price = EXCLUDED.upper_limit_price,
              lower_limit_price = EXCLUDED.lower_limit_price,
              is_halted = EXCLUDED.is_halted,
              auction_imbalance_ratio = EXCLUDED.auction_imbalance_ratio,
              auction_hint_level = EXCLUDED.auction_hint_level
            """
        )

        sh_tz = ZoneInfo("Asia/Shanghai")
        for game_day_no in range(1, game_days + 1):
            day_date = cfg.start_date + timedelta(days=game_day_no - 1)
            day_anchor = datetime(day_date.year, day_date.month, day_date.day, 20, 0, tzinfo=sh_tz)
            tick_ids = build_tick_ids(conn, cfg.season_id, game_day_no, day_anchor)

            batch_rows: list[dict] = []
            for ts_code in universe:
                rows, day_close = seed_symbol_day_rows(
                    ts_code=ts_code,
                    season_id=cfg.season_id,
                    game_day_no=game_day_no,
                    tick_ids=tick_ids,
                    prev_close=prev_close_by_code[ts_code],
                    global_seed=cfg.seed,
                )
                prev_close_by_code[ts_code] = day_close
                batch_rows.extend(rows)

            conn.execute(insert_quotes_sql, batch_rows)

        validate_seeded_data(conn, cfg.season_id, universe_size=len(universe), game_days=game_days)
        print(
            f"seed completed: season_id={cfg.season_id}, game_days={game_days}, "
            f"symbols={len(universe)}, seed={cfg.seed}"
        )


if __name__ == "__main__":
    run(parse_args())
