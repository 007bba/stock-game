"""Fill market_ticks timeline for SeasonScheduler from trading calendar.

Usage:
  python scripts/service/fill_market_ticks.py --season-id 1 --start-date 2026-01-01 --end-date 2026-01-31
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.etl.tushare_pipeline import build_market_ticks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill market_ticks rows for a season")
    parser.add_argument("--season-id", type=int, required=True)
    parser.add_argument("--exchange", default="SSE")
    parser.add_argument("--start-date", help="YYYY-MM-DD, defaults to seasons.start_at::date")
    parser.add_argument("--end-date", help="YYYY-MM-DD, defaults to seasons.end_at::date")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing market_ticks rows for this season before inserting",
    )
    return parser.parse_args()


def get_db_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def resolve_date_range(conn, season_id: int, start_date: str | None, end_date: str | None) -> tuple[str, str]:
    if start_date and end_date:
        return start_date, end_date

    row = conn.execute(
        text(
            """
            SELECT start_at::date::text, end_at::date::text
            FROM seasons
            WHERE id = :season_id
            """
        ),
        {"season_id": season_id},
    ).fetchone()
    if row is None:
        raise RuntimeError(f"season_id={season_id} not found")

    resolved_start = start_date or row[0]
    resolved_end = end_date or row[1]
    if not resolved_start or not resolved_end:
        raise RuntimeError("missing --start-date/--end-date and season start_at/end_at is null")
    return str(resolved_start), str(resolved_end)


def load_open_dates(conn, exchange: str, start_date: str, end_date: str) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT cal_date::text
            FROM trading_calendar
            WHERE exchange = :exchange
              AND cal_date BETWEEN :start_date AND :end_date
              AND is_open = TRUE
            ORDER BY cal_date
            """
        ),
        {"exchange": exchange, "start_date": start_date, "end_date": end_date},
    ).fetchall()
    return [str(row[0]) for row in rows]


def main() -> int:
    args = parse_args()
    engine = create_engine(get_db_url(), future=True)

    with engine.begin() as conn:
        start_date, end_date = resolve_date_range(conn, args.season_id, args.start_date, args.end_date)
        open_dates = load_open_dates(conn, args.exchange, start_date, end_date)
        if not open_dates:
            raise RuntimeError(
                f"no open trade dates found in trading_calendar for exchange={args.exchange} range={start_date}..{end_date}"
            )

        if args.reset:
            conn.execute(
                text(
                    """
                    DELETE FROM market_tick_quotes WHERE season_id = :season_id
                    """
                ),
                {"season_id": args.season_id},
            )
            conn.execute(
                text(
                    """
                    DELETE FROM market_ticks WHERE season_id = :season_id
                    """
                ),
                {"season_id": args.season_id},
            )

        total_ticks = 0
        for game_day_no, cal_date in enumerate(open_dates, start=1):
            day_start = pd.Timestamp(f"{cal_date} 20:00:00+08:00")
            tick_ids = build_market_ticks(conn, args.season_id, game_day_no, day_start)
            total_ticks += len(tick_ids)

        print(
            f"[OK] season_id={args.season_id}, game_days={len(open_dates)}, "
            f"ticks_upserted={total_ticks}, range={start_date}..{end_date}, exchange={args.exchange}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())