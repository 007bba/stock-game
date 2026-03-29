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
import subprocess
import sys
import time as pytime
from dataclasses import dataclass
from datetime import date, time as dt_time
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text

try:
    import tushare as ts
except Exception:  # pragma: no cover
    ts = None


LOGGER = logging.getLogger("tushare_pipeline")

AM_MATCH_MINUTES = (8, 13, 18, 23, 29)
PM_MATCH_MINUTES = (36, 41, 46, 51, 57)
MATCHING_MINUTES = {3, 8, 13, 18, 23, 29, 36, 41, 46, 51, 57, 60}


def round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def split_even_windows(df: pd.DataFrame, windows: int) -> list[pd.DataFrame]:
    if windows <= 0:
        raise ValueError("windows must be > 0")

    if df.empty:
        return [df.copy() for _ in range(windows)]

    total = len(df)
    base = total // windows
    remainder = total % windows
    out = []
    start = 0
    for idx in range(windows):
        size = base + (1 if idx < remainder else 0)
        end = start + size
        out.append(df.iloc[start:end].copy())
        start = end
    return out


def aggregate_window(window_df: pd.DataFrame, fallback_price: float) -> dict:
    if window_df.empty:
        return {
            "open": round_price(fallback_price),
            "high": round_price(fallback_price),
            "low": round_price(fallback_price),
            "close": round_price(fallback_price),
            "vwap": round_price(fallback_price),
            "volume": 0,
            "amount": 0.0,
        }

    open_price = float(window_df.iloc[0]["open_price"])
    high_price = float(window_df["high_price"].max())
    low_price = float(window_df["low_price"].min())
    close_price = float(window_df.iloc[-1]["close_price"])
    volume = int(window_df["vol"].sum())
    amount = float(window_df["amount"].sum())
    vwap = amount / volume if volume > 0 else close_price

    return {
        "open": round_price(open_price),
        "high": round_price(high_price),
        "low": round_price(low_price),
        "close": round_price(close_price),
        "vwap": round_price(vwap),
        "volume": volume,
        "amount": amount,
    }


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


def build_quote_timeline(day_df: pd.DataFrame, prev_close: float, halted: bool) -> dict[int, dict]:
    timeline: dict[int, dict] = {}

    if day_df.empty:
        base_price = prev_close
        upper = round_price(prev_close * 1.1)
        lower = round_price(prev_close * 0.9)
        for minute in range(1, 61):
            timeline[minute] = {
                "ref_price": round_price(base_price),
                "open_price": round_price(base_price),
                "high_price": round_price(base_price),
                "low_price": round_price(base_price),
                "close_price": round_price(base_price),
                "vwap_price": round_price(base_price),
                "volume": 0,
                "volume_factor": 0.1,
                "upper_limit_price": upper,
                "lower_limit_price": lower,
                "is_halted": halted,
                "auction_imbalance_ratio": 0.0,
                "auction_hint_level": 0,
            }
        return timeline

    local_ts = pd.to_datetime(day_df["trade_time"], utc=True).dt.tz_convert("Asia/Shanghai")
    day_df = day_df.assign(local_time=local_ts)

    am_mask = (day_df["local_time"].dt.time >= dt_time(9, 30)) & (day_df["local_time"].dt.time <= dt_time(11, 30))
    pm_mask = (day_df["local_time"].dt.time >= dt_time(13, 0)) & (day_df["local_time"].dt.time <= dt_time(15, 0))
    am_df = day_df.loc[am_mask].copy()
    pm_df = day_df.loc[pm_mask].copy()

    day_open = float(day_df.iloc[0]["open_price"])
    day_close = float(day_df.iloc[-1]["close_price"])
    upper = round_price(prev_close * 1.1)
    lower = round_price(prev_close * 0.9)

    am_windows = split_even_windows(am_df, 5)
    pm_windows = split_even_windows(pm_df, 5)
    am_aggs = [aggregate_window(w, day_open) for w in am_windows]
    pm_aggs = [aggregate_window(w, day_close) for w in pm_windows]

    all_match_volumes = [x["volume"] for x in am_aggs + pm_aggs if x["volume"] > 0]
    avg_match_volume = sum(all_match_volumes) / len(all_match_volumes) if all_match_volumes else 1.0

    open_gap_ratio = 0.0 if prev_close <= 0 else clamp((day_open - prev_close) / max(prev_close * 0.1, 0.001), -1.0, 1.0)
    close_gap_ratio = 0.0 if prev_close <= 0 else clamp((day_close - prev_close) / max(prev_close * 0.1, 0.001), -1.0, 1.0)

    def mk_quote(ref_price: float, agg: dict | None, is_auction: bool, imbalance_ratio: float) -> dict:
        safe_ref = round_price(clamp(ref_price, lower, upper))
        base = agg or aggregate_window(pd.DataFrame(), safe_ref)
        vol_factor = clamp((base["volume"] / avg_match_volume) if avg_match_volume > 0 else 1.0, 0.1, 3.0)
        hint = compute_hint_level(safe_ref, prev_close, imbalance_ratio) if is_auction else 0
        return {
            "ref_price": safe_ref,
            "open_price": round_price(clamp(base["open"], lower, upper)),
            "high_price": round_price(clamp(base["high"], lower, upper)),
            "low_price": round_price(clamp(base["low"], lower, upper)),
            "close_price": round_price(clamp(base["close"], lower, upper)),
            "vwap_price": round_price(clamp(base["vwap"], lower, upper)),
            "volume": int(base["volume"]),
            "volume_factor": round(clamp(vol_factor, 0.1, 3.0), 6),
            "upper_limit_price": upper,
            "lower_limit_price": lower,
            "is_halted": halted,
            "auction_imbalance_ratio": round(float(imbalance_ratio), 6),
            "auction_hint_level": hint,
        }

    o1 = prev_close * 0.67 + day_open * 0.33
    o2 = prev_close * 0.33 + day_open * 0.67
    timeline[1] = mk_quote(o1, None, True, open_gap_ratio)
    timeline[2] = mk_quote(o2, None, True, open_gap_ratio)
    timeline[3] = mk_quote(day_open, am_aggs[0], True, open_gap_ratio)

    last_quote = timeline[3]
    am_minute_to_window = {8: 0, 13: 1, 18: 2, 23: 3, 29: 4}
    pm_minute_to_window = {36: 0, 41: 1, 46: 2, 51: 3, 57: 4}

    for minute in range(4, 30):
        if minute in am_minute_to_window:
            agg = am_aggs[am_minute_to_window[minute]]
            last_quote = mk_quote(agg["close"], agg, False, 0.0)
        else:
            last_quote = {**last_quote, "volume": 0, "volume_factor": 0.1}
        timeline[minute] = last_quote

    timeline[30] = {**last_quote, "volume": 0, "volume_factor": 0.1}
    timeline[31] = {**last_quote, "volume": 0, "volume_factor": 0.1}

    last_quote = timeline[31]
    for minute in range(32, 58):
        if minute in pm_minute_to_window:
            agg = pm_aggs[pm_minute_to_window[minute]]
            last_quote = mk_quote(agg["close"], agg, False, 0.0)
        else:
            last_quote = {**last_quote, "volume": 0, "volume_factor": 0.1}
        timeline[minute] = last_quote

    c58 = last_quote["ref_price"] * 0.67 + day_close * 0.33
    c59 = last_quote["ref_price"] * 0.33 + day_close * 0.67
    close_agg = aggregate_window(pm_df.tail(3), day_close)
    timeline[58] = mk_quote(c58, None, True, close_gap_ratio)
    timeline[59] = mk_quote(c59, None, True, close_gap_ratio)
    timeline[60] = mk_quote(day_close, close_agg, True, close_gap_ratio)

    if halted:
        for minute in range(1, 61):
            timeline[minute]["volume"] = 0
            timeline[minute]["volume_factor"] = 0.1

    return timeline


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
    parser.add_argument("--start-date", help="YYYY-MM-DD")
    parser.add_argument("--end-date", help="YYYY-MM-DD")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["calendar", "bars", "halts", "actions", "compress", "validate", "all"],
    )
    args = parser.parse_args()

    if args.mode != "validate" and (not args.start_date or not args.end_date):
        parser.error("--start-date and --end-date are required unless --mode validate")

    return Config(
        season_id=args.season_id,
        start_date=args.start_date or "",
        end_date=args.end_date or "",
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

    # Prefer token-only client init to avoid writing tk.csv in restricted environments.
    try:
        return ts.pro_api(token=token)
    except TypeError:
        ts.set_token(token)
        return ts.pro_api()

RETRYABLE_TUSHARE_KEYWORDS = (
    "每分钟最多访问",
    "每小时最多访问",
    "每天最多访问",
    "too many requests",
    "timeout",
    "temporarily",
    "connection reset",
    "connection aborted",
)


def is_retryable_tushare_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(keyword.lower() in message for keyword in RETRYABLE_TUSHARE_KEYWORDS)


def call_tushare_with_retry(api_name: str, func, retries: int = 3, base_sleep_seconds: int = 5, **kwargs):
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return func(**kwargs)
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            retryable = is_retryable_tushare_error(exc)
            if attempt >= retries or not retryable:
                raise

            wait_seconds = base_sleep_seconds * attempt
            LOGGER.warning(
                "%s failed attempt %s/%s: %s; retry in %ss",
                api_name,
                attempt,
                retries,
                exc,
                wait_seconds,
            )
            pytime.sleep(wait_seconds)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{api_name} failed without exception")


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


def load_day_bars(conn, ts_code: str, trade_date: str) -> pd.DataFrame:
    sql = text(
        """
        SELECT trade_time, open_price, high_price, low_price, close_price, vol, amount
        FROM raw_minute_bars
        WHERE ts_code = :ts_code
          AND trade_date = :trade_date
        ORDER BY trade_time ASC
        """
    )
    return pd.read_sql_query(sql, conn, params={"ts_code": ts_code, "trade_date": trade_date})


def load_prev_close(conn, ts_code: str, trade_date: str) -> float | None:
    sql = text(
        """
        SELECT close_price
        FROM raw_minute_bars
        WHERE ts_code = :ts_code
          AND trade_date < :trade_date
        ORDER BY trade_time DESC
        LIMIT 1
        """
    )
    row = conn.execute(sql, {"ts_code": ts_code, "trade_date": trade_date}).fetchone()
    return float(row[0]) if row else None


def load_halted_codes(conn, trade_date: str) -> set[str]:
    sql = text(
        """
        SELECT s.ts_code
        FROM trading_halts s
        WHERE s.trade_date = :trade_date
          AND s.suspend_type = 'S'
          AND NOT EXISTS (
            SELECT 1
            FROM trading_halts r
            WHERE r.ts_code = s.ts_code
              AND r.trade_date = s.trade_date
              AND r.suspend_type = 'R'
          )
        """
    )
    rows = conn.execute(sql, {"trade_date": trade_date}).fetchall()
    return {str(r[0]) for r in rows}


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
            try:
                with engine.begin() as conn2:
                    finish_etl_job(conn2, job_id, "failed", error_message=str(exc))
            except Exception:
                LOGGER.exception("failed to update etl_jobs status after exception")
            raise



def _normalize_minute_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    cols = {c.lower(): c for c in df.columns}

    # Common candidates from different minute endpoints.
    time_col = cols.get("trade_time") or cols.get("datetime") or cols.get("trade_date")
    open_col = cols.get("open")
    high_col = cols.get("high")
    low_col = cols.get("low")
    close_col = cols.get("close")
    vol_col = cols.get("vol") or cols.get("volume")
    amount_col = cols.get("amount") or cols.get("amt")

    required = [time_col, open_col, high_col, low_col, close_col]
    if any(c is None for c in required):
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "trade_time": pd.to_datetime(df[time_col], utc=False),
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "vol": pd.to_numeric(df[vol_col], errors="coerce") if vol_col else 0,
            "amount": pd.to_numeric(df[amount_col], errors="coerce") if amount_col else 0,
        }
    )
    out = out.dropna(subset=["trade_time", "open", "high", "low", "close"])

    # Localize to Asia/Shanghai if timezone naive, then convert to UTC for DB timestamptz consistency.
    if out["trade_time"].dt.tz is None:
        out["trade_time"] = out["trade_time"].dt.tz_localize("Asia/Shanghai")
    out["trade_time"] = out["trade_time"].dt.tz_convert("UTC")

    out = out.sort_values("trade_time").reset_index(drop=True)
    return out

def parse_maybe_date(value) -> date | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "nan":
        return None
    parsed = pd.to_datetime(text_value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def normalize_halts_df(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"])

    cols = {c.lower(): c for c in df.columns}
    suspend_date_col = cols.get("suspend_date") or cols.get("trade_date")
    resume_date_col = cols.get("resume_date")
    timing_col = cols.get("suspend_timing") or cols.get("timing")

    rows: list[dict] = []
    for _, row in df.iterrows():
        timing = str(row[timing_col]).strip() if timing_col and pd.notna(row[timing_col]) else ""
        suspend_date = parse_maybe_date(row[suspend_date_col]) if suspend_date_col else None
        resume_date = parse_maybe_date(row[resume_date_col]) if resume_date_col else None
        if suspend_date is not None:
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": suspend_date,
                    "suspend_type": "S",
                    "suspend_timing": timing,
                }
            )
        if resume_date is not None:
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": resume_date,
                    "suspend_type": "R",
                    "suspend_timing": timing,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"])
    return out.drop_duplicates(subset=["ts_code", "trade_date", "suspend_type", "suspend_timing"])


def _normalize_daily_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    cols = {c.lower(): c for c in df.columns}
    trade_date_col = cols.get("trade_date")
    open_col = cols.get("open")
    high_col = cols.get("high")
    low_col = cols.get("low")
    close_col = cols.get("close")
    vol_col = cols.get("vol") or cols.get("volume")
    amount_col = cols.get("amount") or cols.get("amt")

    required = [trade_date_col, open_col, high_col, low_col, close_col]
    if any(c is None for c in required):
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(df[trade_date_col], errors="coerce").dt.date,
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "vol": pd.to_numeric(df[vol_col], errors="coerce") if vol_col else 0,
            "amount": pd.to_numeric(df[amount_col], errors="coerce") if amount_col else 0,
        }
    )
    out = out.dropna(subset=["trade_date", "open", "high", "low", "close"])
    return out.sort_values("trade_date").reset_index(drop=True)


def _synthesize_minute_from_daily(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for _, row in daily_df.iterrows():
        d = row["trade_date"]
        open_p = float(row["open"])
        high_p = float(row["high"])
        low_p = float(row["low"])
        close_p = float(row["close"])
        total_vol = int(max(float(row.get("vol", 0) or 0), 0))
        total_amount = float(max(float(row.get("amount", 0) or 0), 0))

        if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
            continue

        am_times = pd.date_range(f"{d} 09:30:00", periods=120, freq="min", tz="Asia/Shanghai")
        pm_times = pd.date_range(f"{d} 13:00:00", periods=120, freq="min", tz="Asia/Shanghai")
        minute_times = list(am_times) + list(pm_times)
        points = len(minute_times)

        vol_base = total_vol // points if points > 0 else 0
        vol_rem = total_vol % points if points > 0 else 0
        amt_base = total_amount / points if points > 0 else 0.0

        prev = open_p
        for idx, ts_local in enumerate(minute_times):
            frac = (idx + 1) / points
            target = open_p + (close_p - open_p) * frac
            open_m = prev
            close_m = target
            high_m = max(open_m, close_m)
            low_m = min(open_m, close_m)

            if idx == points // 3:
                high_m = max(high_m, high_p)
            if idx == (points * 2) // 3:
                low_m = min(low_m, low_p)

            rows.append(
                {
                    "trade_time": ts_local.tz_convert("UTC"),
                    "open": float(open_m),
                    "high": float(high_m),
                    "low": float(low_m),
                    "close": float(close_m),
                    "vol": int(vol_base + (1 if idx < vol_rem else 0)),
                    "amount": float(amt_base),
                }
            )
            prev = close_m

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    return out.sort_values("trade_time").reset_index(drop=True)


def fetch_minute_bars(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Try multiple Tushare interfaces by entitlement, with daily fallback synthesis."""
    start_n = start_date.replace("-", "")
    end_n = end_date.replace("-", "")

    # 1) Preferred: account-enabled minute endpoint on pro API.
    try:
        if hasattr(pro, "stk_mins"):
            raw = pro.stk_mins(ts_code=ts_code, start_date=start_n, end_date=end_n, freq="1min")
            df = _normalize_minute_df(raw)
            if not df.empty:
                return df
    except Exception as exc:
        LOGGER.warning("stk_mins failed for %s: %s", ts_code, exc)

    # 2) Fallback: ts.pro_bar
    try:
        if ts is not None and hasattr(ts, "pro_bar"):
            raw = ts.pro_bar(
                ts_code=ts_code,
                start_date=start_n,
                end_date=end_n,
                freq="1min",
                asset="E",
                adj=None,
            )
            df = _normalize_minute_df(raw)
            if not df.empty:
                return df
    except Exception as exc:
        LOGGER.warning("pro_bar failed for %s: %s", ts_code, exc)

    # 3) Last fallback: daily bars expanded to pseudo-minute bars.
    try:
        if hasattr(pro, "daily"):
            raw = pro.daily(ts_code=ts_code, start_date=start_n, end_date=end_n)
            daily_df = _normalize_daily_df(raw)
            df = _synthesize_minute_from_daily(daily_df)
            if not df.empty:
                LOGGER.warning("using daily->minute fallback for %s", ts_code)
                return df
    except Exception as exc:
        LOGGER.warning("daily fallback failed for %s: %s", ts_code, exc)

    return pd.DataFrame()

def sync_minute_bars(cfg: Config):
    """Sync minute bars into raw_minute_bars.

    Note: Tushare minute endpoint varies by entitlement; function tries
    stk_mins first and pro_bar second.
    """
    _pro = get_tushare_pro()
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    if not universe:
        raise RuntimeError("season_universe is empty")

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "minute_bars_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            records = 0
            for ts_code in universe:
                df = fetch_minute_bars(_pro, ts_code, cfg.start_date, cfg.end_date)

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
            try:
                with engine.begin() as conn2:
                    finish_etl_job(conn2, job_id, "failed", error_message=str(exc))
            except Exception:
                LOGGER.exception("failed to update etl_jobs status after exception")
            raise


def sync_halts(cfg: Config):
    pro = get_tushare_pro()
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    if not universe:
        raise RuntimeError("season_universe is empty")

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "halts_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            if not hasattr(pro, "suspend_d"):
                LOGGER.warning("suspend_d not available in current tushare client; skip halts sync")
                finish_etl_job(conn, job_id, "succeeded", row_count=0)
                return

            records = 0
            for ts_code in universe:
                try:
                    raw = pro.suspend_d(
                        ts_code=ts_code,
                        start_date=cfg.start_date.replace("-", ""),
                        end_date=cfg.end_date.replace("-", ""),
                    )
                except Exception as exc:
                    LOGGER.warning("suspend_d failed for %s: %s", ts_code, exc)
                    continue

                normalized = normalize_halts_df(raw, ts_code)
                if normalized.empty:
                    continue

                for _, row in normalized.iterrows():
                    conn.execute(
                        text(
                            """
                            INSERT INTO trading_halts (ts_code, trade_date, suspend_type, suspend_timing)
                            VALUES (:ts_code, :trade_date, :suspend_type, :suspend_timing)
                            ON CONFLICT (ts_code, trade_date, suspend_type, suspend_timing)
                            DO NOTHING
                            """
                        ),
                        {
                            "ts_code": row["ts_code"],
                            "trade_date": row["trade_date"],
                            "suspend_type": row["suspend_type"],
                            "suspend_timing": row["suspend_timing"],
                        },
                    )
                    records += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=records)
        except Exception as exc:  # pragma: no cover
            try:
                with engine.begin() as conn2:
                    finish_etl_job(conn2, job_id, "failed", error_message=str(exc))
            except Exception:
                LOGGER.exception("failed to update etl_jobs status after exception")
            raise

def normalize_adj_factor_df(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["trade_date", "adj_factor"])

    cols = {c.lower(): c for c in df.columns}
    trade_date_col = cols.get("trade_date")
    adj_factor_col = cols.get("adj_factor")
    if trade_date_col is None or adj_factor_col is None:
        return pd.DataFrame(columns=["trade_date", "adj_factor"])

    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(df[trade_date_col], errors="coerce").dt.date,
            "adj_factor": pd.to_numeric(df[adj_factor_col], errors="coerce"),
        }
    ).dropna(subset=["trade_date", "adj_factor"])

    if start_date:
        start_d = pd.to_datetime(start_date).date()
        out = out.loc[out["trade_date"] >= start_d]
    if end_date:
        end_d = pd.to_datetime(end_date).date()
        out = out.loc[out["trade_date"] <= end_d]

    return out.sort_values("trade_date").drop_duplicates(subset=["trade_date"]).reset_index(drop=True)


def fetch_adj_factor(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    if not hasattr(pro, "adj_factor"):
        LOGGER.warning("adj_factor not available in current tushare client; skip actions for %s", ts_code)
        return pd.DataFrame(columns=["trade_date", "adj_factor"])

    start_n = start_date.replace("-", "") if start_date else ""
    end_n = end_date.replace("-", "") if end_date else ""

    # Strategy 1: query with date range.
    try:
        raw = call_tushare_with_retry(
            "adj_factor",
            pro.adj_factor,
            retries=3,
            base_sleep_seconds=8,
            ts_code=ts_code,
            start_date=start_n,
            end_date=end_n,
        )
        normalized = normalize_adj_factor_df(raw, start_date, end_date)
        if not normalized.empty:
            return normalized
    except Exception as exc:
        LOGGER.warning("adj_factor range query failed for %s: %s", ts_code, exc)

    # Strategy 2: degrade to full-history query then filter locally.
    try:
        raw = call_tushare_with_retry(
            "adj_factor_full",
            pro.adj_factor,
            retries=2,
            base_sleep_seconds=10,
            ts_code=ts_code,
        )
        normalized = normalize_adj_factor_df(raw, start_date, end_date)
        if not normalized.empty:
            LOGGER.warning("using full-history adj_factor fallback for %s", ts_code)
            return normalized
    except Exception as exc:
        LOGGER.warning("adj_factor full query failed for %s: %s", ts_code, exc)

    return pd.DataFrame(columns=["trade_date", "adj_factor"])


def sync_actions(cfg: Config):
    pro = get_tushare_pro()
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    if not universe:
        raise RuntimeError("season_universe is empty")

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "action_sync", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
            records = 0
            skipped_codes = 0

            for ts_code in universe:
                df = fetch_adj_factor(pro, ts_code, cfg.start_date, cfg.end_date)
                if df.empty:
                    skipped_codes += 1
                    LOGGER.warning("No adj_factor data for %s in range", ts_code)
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
                            "ex_date": row["trade_date"],
                            "adjust_factor": float(row["adj_factor"]),
                            "raw_payload": row.to_json(force_ascii=False),
                        },
                    )
                    records += 1

            if skipped_codes > 0:
                LOGGER.warning("sync_actions skipped %s/%s codes due to unavailable adj_factor", skipped_codes, len(universe))

            finish_etl_job(conn, job_id, "succeeded", row_count=records)
        except Exception as exc:  # pragma: no cover
            try:
                with engine.begin() as conn2:
                    finish_etl_job(conn2, job_id, "failed", error_message=str(exc))
            except Exception:
                LOGGER.exception("failed to update etl_jobs status after exception")
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
            mode = "batch_match" if minute in set(AM_MATCH_MINUTES) else "accept_only"
            tradable = True
            matching = minute in set(AM_MATCH_MINUTES)
        elif 30 <= minute <= 31:
            phase = "lunch_break"
            mode = "frozen"
            tradable = False
            matching = False
        elif 32 <= minute <= 57:
            phase = "pm_continuous"
            mode = "batch_match" if minute in set(PM_MATCH_MINUTES) else "accept_only"
            tradable = True
            matching = minute in set(PM_MATCH_MINUTES)
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
                "scheduled_at": (day_start_ts + pd.Timedelta(minutes=minute - 1)).to_pydatetime(),
            },
        ).fetchone()
        tick_ids.append(int(row[0]))

    return tick_ids


def compress_season(cfg: Config):
    """Build timeline and quote snapshots for replay using raw minute bars."""
    engine = get_engine()
    universe = load_universe(engine, cfg.season_id)

    if not universe:
        raise RuntimeError("season_universe is empty")

    with engine.begin() as conn:
        job_id = create_etl_job(conn, "season_compress", cfg.season_id, cfg.start_date, cfg.end_date)
        try:
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
                halted_codes = load_halted_codes(conn, cal_date)

                for ts_code in universe:
                    day_df = load_day_bars(conn, ts_code, cal_date)
                    prev_close = load_prev_close(conn, ts_code, cal_date)
                    if prev_close is None:
                        if day_df.empty:
                            LOGGER.warning("No bars and no prev close for %s on %s; skip", ts_code, cal_date)
                            continue
                        prev_close = float(day_df.iloc[0]["open_price"])

                    quote_timeline = build_quote_timeline(
                        day_df=day_df,
                        prev_close=float(prev_close),
                        halted=ts_code in halted_codes,
                    )

                    for minute, tick_id in enumerate(tick_ids, start=1):
                        quote = quote_timeline[minute]
                        conn.execute(
                            text(
                                """
                                INSERT INTO market_tick_quotes (
                                  tick_id, season_id, ts_code, ref_price,
                                  open_price, high_price, low_price, close_price, vwap_price,
                                  upper_limit_price, lower_limit_price, is_halted,
                                  volume, volume_factor, auction_imbalance_ratio, auction_hint_level
                                ) VALUES (
                                  :tick_id, :season_id, :ts_code, :ref_price,
                                  :open_price, :high_price, :low_price, :close_price, :vwap_price,
                                  :upper_limit_price, :lower_limit_price, :is_halted,
                                  :volume, :volume_factor, :auction_imbalance_ratio, :auction_hint_level
                                )
                                """
                            ),
                            {
                                "tick_id": tick_id,
                                "season_id": cfg.season_id,
                                "ts_code": ts_code,
                                "ref_price": quote["ref_price"],
                                "open_price": quote["open_price"],
                                "high_price": quote["high_price"],
                                "low_price": quote["low_price"],
                                "close_price": quote["close_price"],
                                "vwap_price": quote["vwap_price"],
                                "upper_limit_price": quote["upper_limit_price"],
                                "lower_limit_price": quote["lower_limit_price"],
                                "is_halted": quote["is_halted"],
                                "volume": quote["volume"],
                                "volume_factor": quote["volume_factor"],
                                "auction_imbalance_ratio": quote["auction_imbalance_ratio"],
                                "auction_hint_level": quote["auction_hint_level"],
                            },
                        )
                        row_count += 1

            finish_etl_job(conn, job_id, "succeeded", row_count=row_count)
        except Exception as exc:  # pragma: no cover
            try:
                with engine.begin() as conn2:
                    finish_etl_job(conn2, job_id, "failed", error_message=str(exc))
            except Exception:
                LOGGER.exception("failed to update etl_jobs status after exception")
            raise

def run_compression_validation(cfg: Config):
    script_path = os.path.join(os.path.dirname(__file__), "validate_compression.py")
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    report_path = os.path.join(repo_root, "docs", "reports", f"validation-season-{cfg.season_id}.json")
    command = [
        sys.executable,
        script_path,
        "--mode",
        "db",
        "--season-id",
        str(cfg.season_id),
        "--report-out",
        report_path,
    ]
    LOGGER.info("run compression validation: %s", " ".join(command))
    subprocess.run(command, check=True)



def run(cfg: Config):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if cfg.mode in ("calendar", "all"):
        LOGGER.info("sync_calendar start")
        sync_calendar(cfg)

    if cfg.mode in ("bars", "all"):
        LOGGER.info("sync_minute_bars start")
        sync_minute_bars(cfg)

    if cfg.mode in ("halts", "all"):
        LOGGER.info("sync_halts start")
        sync_halts(cfg)

    if cfg.mode in ("actions", "all"):
        LOGGER.info("sync_actions start")
        sync_actions(cfg)

    if cfg.mode in ("compress", "all"):
        LOGGER.info("compress_season start")
        compress_season(cfg)

    if cfg.mode in ("validate", "all"):
        LOGGER.info("validate_compression start")
        run_compression_validation(cfg)


if __name__ == "__main__":
    run(parse_args())

