"""Tushare ETL pipeline scaffold for Stock Game MVP.

Usage:
  python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-01 --end-date 2026-01-31

Required env vars:
  TUSHARE_TOKEN
  DATABASE_URL
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text

try:
    import tushare as ts
except Exception:  # pragma: no cover
    ts = None


LOGGER = logging.getLogger("tushare_pipeline")


@dataclass
class Config:
    season_id: int
    start_date: str
    end_date: str
    mode: str
    exchange: str = "SSE"


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Tushare ETL pipeline")
    parser.add_argument("--season-id", type=int, required=True)
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["calendar", "bars", "actions", "compress", "all"],
    )
    args = parser.parse_args()
    return Config(
        season_id=args.season_id,
        start_date=args.start_date,
        end_date=args.end_date,
        mode=args.mode,
    )


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return create_engine(database_url, future=True)


def get_tushare_pro():
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required")
    if ts is None:
        raise RuntimeError("tushare package is not installed")
    ts.set_token(token)
    return ts.pro_api()


def create_etl_job(conn, job_type: str, season_id: int, start_date: str, end_date: str) -> int:
    sql = text(
        """
        INSERT INTO etl_jobs (job_type, season_id, start_date, end_date, status, started_at)
        VALUES (:job_type, :season_id, :start_date, :end_date, 'running', now())
        RETURNING id
        """
    )
    row = conn.execute(
        sql,
        {
            "job_type": job_type,
            "season_id": season_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).fetchone()
    return int(row[0])


def finish_etl_job(conn, job_id: int, status: str, row_count: int = 0, error_message: str | None = None):
    conn.execute(
        text(
            """
            UPDATE etl_jobs
            SET status = :status,
                row_count = :row_count,
                error_message = :error_message,
                finished_at = now()
            WHERE id = :job_id
            """
        ),
        {
            "status": status,
            "row_count": row_count,
            "error_message": error_message,
            "job_id": job_id,
        },
    )


def iter_trade_dates(engine, exchange: str, start_date: str, end_date: str) -> Iterable[str]:
    sql = text(
        """
        SELECT cal_date::text
        FROM trading_calendar
        WHERE exchange = :exchange
          AND cal_date BETWEEN :start_date AND :end_date
          AND is_open = TRUE
        ORDER BY cal_date
        """
    )
    with engine.begin() as conn:
        for row in conn.execute(
            sql,
            {"exchange": exchange, "start_date": start_date, "end_date": end_date},
        ):
            yield str(row[0])


def load_universe(engine, season_id: int) -> list[str]:
    sql = text(
        """
        SELECT ts_code
        FROM season_universe
        WHERE season_id = :season_id AND is_active = TRUE
        ORDER BY rank_in_theme ASC
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(sql, {"season_id": season_id}).fetchall()
    return [str(r[0]) for r in rows]


def sync_calendar(cfg: Config):
    pro = get_tushare_pro()
    engine = get_engine()

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "calendar_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            df = pro.trade_cal(
                exchange=cfg.exchange,
                start_date=cfg.start_date.replace("-", ""),
                end_date=cfg.end_date.replace("-", ""),
            )
            if df is None or df.empty:
                finish_etl_job(conn, job_id, "succeeded", row_count=0)
                return

            records = 0
            for _, row in df.iterrows():
                conn.execute(
                    text(
                        """
                        INSERT INTO trading_calendar (exchange, cal_date, is_open, pretrade_date)
                        VALUES (:exchange, :cal_date, :is_open, :pretrade_date)
                        ON CONFLICT (exchange, cal_date)
                        DO UPDATE SET
                          is_open = EXCLUDED.is_open,
                          pretrade_date = EXCLUDED.pretrade_date
                        """
                    ),
                    {
                        "exchange": row["exchange"] or cfg.exchange,
                        "cal_date": pd.to_datetime(row["cal_date"]).date(),
                        "is_open": str(row["is_open"]) == "1",
                        "pretrade_date": pd.to_datetime(row["pretrade_date"]).date()
                        if row.get("pretrade_date")
                        else None,
                    },
                )
                records += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=records)
        except Exception as exc:  # pragma: no cover
            finish_etl_job(conn, job_id, "failed", error_message=str(exc))
            raise


def sync_minute_bars(cfg: Config):
    """Sync minute bars into raw_minute_bars.

    Note: Tushare minute endpoint may vary by account entitlement.
    Replace fetch logic below with the endpoint enabled in your account.
    """
    pro = get_tushare_pro()
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    if not universe:
        raise RuntimeError("season_universe is empty")

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "minute_bars_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            records = 0
            for ts_code in universe:
                # TODO: replace with your enabled minute API call.
                # Example placeholder:
                # df = pro.stk_mins(ts_code=ts_code, start_date='20260101', end_date='20260131', freq='1min')
                df = pd.DataFrame()

                if df.empty:
                    LOGGER.warning("No minute bars for %s in range", ts_code)
                    continue

                for _, row in df.iterrows():
                    trade_time = pd.to_datetime(row["trade_time"])
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
                              :vol, :amount, 'tushare'
                            )
                            ON CONFLICT (ts_code, trade_time)
                            DO UPDATE SET
                              open_price = EXCLUDED.open_price,
                              high_price = EXCLUDED.high_price,
                              low_price = EXCLUDED.low_price,
                              close_price = EXCLUDED.close_price,
                              vol = EXCLUDED.vol,
                              amount = EXCLUDED.amount
                            """
                        ),
                        {
                            "ts_code": ts_code,
                            "trade_time": trade_time.to_pydatetime(),
                            "trade_date": trade_time.date(),
                            "open_price": float(row["open"]),
                            "high_price": float(row["high"]),
                            "low_price": float(row["low"]),
                            "close_price": float(row["close"]),
                            "vol": int(row.get("vol", 0)),
                            "amount": float(row.get("amount", 0)),
                        },
                    )
                    records += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=records)
        except Exception as exc:  # pragma: no cover
            finish_etl_job(conn, job_id, "failed", error_message=str(exc))
            raise


def sync_actions(cfg: Config):
    pro = get_tushare_pro()
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "action_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            records = 0
            for ts_code in universe:
                # Placeholder: adjust according to enabled interfaces (adj_factor/dividend/...)
                df = pro.adj_factor(
                    ts_code=ts_code,
                    start_date=cfg.start_date.replace("-", ""),
                    end_date=cfg.end_date.replace("-", ""),
                )
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    conn.execute(
                        text(
                            """
                            INSERT INTO corp_actions (ts_code, ex_date, action_type, adjust_factor, raw_payload)
                            VALUES (:ts_code, :ex_date, 'adj_factor', :adjust_factor, :raw_payload)
                            ON CONFLICT (ts_code, ex_date, action_type)
                            DO UPDATE SET adjust_factor = EXCLUDED.adjust_factor,
                                          raw_payload = EXCLUDED.raw_payload
                            """
                        ),
                        {
                            "ts_code": ts_code,
                            "ex_date": pd.to_datetime(row["trade_date"]).date(),
                            "adjust_factor": float(row["adj_factor"]),
                            "raw_payload": row.to_json(force_ascii=False),
                        },
                    )
                    records += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=records)
        except Exception as exc:  # pragma: no cover
            finish_etl_job(conn, job_id, "failed", error_message=str(exc))
            raise


def build_market_ticks(conn, season_id: int, game_day_no: int, day_start_ts: pd.Timestamp) -> list[int]:
    """Create 60-minute timeline and return inserted tick IDs in order."""
    tick_ids: list[int] = []

    def minute_meta(minute: int):
        if 1 <= minute <= 3:
            phase = "open_auction"
            mode = "accept_only" if minute < 3 else "open_call_auction"
            tradable = True
            matching = minute == 3
        elif 4 <= minute <= 29:
            phase = "am_continuous"
            mode = "batch_match" if minute in {8, 13, 18, 23, 29} else "accept_only"
            tradable = True
            matching = minute in {8, 13, 18, 23, 29}
        elif 30 <= minute <= 31:
            phase = "lunch_break"
            mode = "frozen"
            tradable = False
            matching = False
        elif 32 <= minute <= 57:
            phase = "pm_continuous"
            mode = "batch_match" if minute in {36, 41, 46, 51, 57} else "accept_only"
            tradable = True
            matching = minute in {36, 41, 46, 51, 57}
        else:
            phase = "close_auction"
            mode = "accept_only" if minute < 60 else "close_call_auction"
            tradable = True
            matching = minute == 60
        return phase, mode, tradable, matching

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
                  :phase::session_phase, :matching_mode::matching_mode,
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
                "scheduled_at": (day_start_ts + pd.Timedelta(minutes=minute - 1)).to_pydatetime(),
            },
        ).fetchone()
        tick_ids.append(int(row[0]))

    return tick_ids


def compress_season(cfg: Config):
    """Build timeline and placeholder quotes for replay.

    This scaffold creates the 60-minute timeline. You should replace quote aggregation
    with real window aggregation per docs/specs/tushare-etl-compression.md.
    """
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "season_compress", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            # clean old compressed data in range for idempotent rebuild
            conn.execute(
                text(
                    """
                    DELETE FROM market_tick_quotes
                    WHERE season_id = :season_id
                    """
                ),
                {"season_id": cfg.season_id},
            )
            conn.execute(
                text(
                    """
                    DELETE FROM market_ticks
                    WHERE season_id = :season_id
                    """
                ),
                {"season_id": cfg.season_id},
            )

            row_count = 0
            open_dates = list(iter_trade_dates(engine, cfg.exchange, cfg.start_date, cfg.end_date))

            for game_day_no, cal_date in enumerate(open_dates, start=1):
                day_start = pd.Timestamp(f"{cal_date} 20:00:00+08:00")
                tick_ids = build_market_ticks(conn, cfg.season_id, game_day_no, day_start)

                for tick_id in tick_ids:
                    for ts_code in universe:
                        # TODO: Replace placeholder values with real aggregated values.
                        conn.execute(
                            text(
                                """
                                INSERT INTO market_tick_quotes (
                                  tick_id, season_id, ts_code, ref_price, vwap_price,
                                  upper_limit_price, lower_limit_price, is_halted,
                                  volume, volume_factor, auction_hint_level
                                ) VALUES (
                                  :tick_id, :season_id, :ts_code, :ref_price, :vwap_price,
                                  :upper_limit_price, :lower_limit_price, :is_halted,
                                  :volume, :volume_factor, :auction_hint_level
                                )
                                """
                            ),
                            {
                                "tick_id": tick_id,
                                "season_id": cfg.season_id,
                                "ts_code": ts_code,
                                "ref_price": 1.000,
                                "vwap_price": 1.000,
                                "upper_limit_price": 1.100,
                                "lower_limit_price": 0.900,
                                "is_halted": False,
                                "volume": 0,
                                "volume_factor": 1.0,
                                "auction_hint_level": 0,
                            },
                        )
                        row_count += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=row_count)
        except Exception as exc:  # pragma: no cover
            finish_etl_job(conn, job_id, "failed", error_message=str(exc))
            raise


def run(cfg: Config):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if cfg.mode in ("calendar", "all"):
        LOGGER.info("sync_calendar start")
        sync_calendar(cfg)

    if cfg.mode in ("bars", "all"):
        LOGGER.info("sync_minute_bars start")
        sync_minute_bars(cfg)

    if cfg.mode in ("actions", "all"):
        LOGGER.info("sync_actions start")
        sync_actions(cfg)

    if cfg.mode in ("compress", "all"):
        LOGGER.info("compress_season start")
        compress_season(cfg)


if __name__ == "__main__":
    run(parse_args())
