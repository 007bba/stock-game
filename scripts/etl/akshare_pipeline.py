"""
AKShare/BaoStock ETL pipeline — 免费 A 股分钟级行情导入。

数据源优先级:
  1. BaoStock 5 分钟线（全历史，免费无限制）— 推荐
  2. AKShare 日线 + 合成伪分钟线（降级方案）

Usage:
  # 按赛季导入（从 season_universe 读取股票池）
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31

  # 指定股票列表
  python scripts/etl/akshare_pipeline.py --start-date 2025-12-01 --end-date 2025-12-31 --codes 000547.SZ,002792.SZ

  # 日线降级（如果 BaoStock 不可用）
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --source akshare-daily

  # 只导入单个日期范围
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-05

  # 预览模式
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --dry-run

  # 清空已有数据并重新导入
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --overwrite

Required env vars:
  DATABASE_URL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time as pytime
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

try:
    import baostock as bs
    HAS_BAOSTOCK = True
except ImportError:
    HAS_BAOSTOCK = False

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

# Add project root to path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

LOGGER = logging.getLogger("akshare_pipeline")


def round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def ts_code_to_baostock(ts_code: str) -> str:
    """000547.SZ -> sz.000547, 600105.SH -> sh.600105"""
    code, market = ts_code.split(".")
    prefix = "sh" if market == "SH" else "sz"
    return f"{prefix}.{code}"


def ts_code_to_akshare(ts_code: str) -> str:
    """000547.SZ -> 000547"""
    return ts_code.split(".")[0]


# ─── BaoStock 数据源 ────────────────────────────────────────────────

def fetch_baostock_5min(bs_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    通过 BaoStock 获取 5 分钟 K 线。
    - 全历史数据，免费无限制
    - 每天 48 条（上午 24 + 下午 24）
    """
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,time,open,high,low,close,volume,amount",
        start_date=start_date,
        end_date=end_date,
        frequency="5",
        adjustflag="3",  # 不复权
    )

    rows = []
    while rs.next():
        row = rs.get_row_data()
        if row[0] and row[2]:  # date and open 非空
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=rs.fields)
    return df


def normalize_baostock_5min(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """将 BaoStock 5 分钟线转为 raw_minute_bars 格式。"""
    if df is None or df.empty:
        return pd.DataFrame()

    result_rows = []
    for _, row in df.iterrows():
        trade_date_str = str(row["date"])
        time_str = str(row["time"])

        open_p = float(row["open"])
        high_p = float(row["high"])
        low_p = float(row["low"])
        close_p = float(row["close"])
        vol = float(row["volume"])   # BaoStock 的 volume 单位是股
        amount = float(row["amount"])  # 元

        if open_p <= 0 or close_p <= 0:
            continue

        # 解析时间: "20251201093500000" -> "2025-12-01 09:35:00"
        # BaoStock time 格式固定 17 位: YYYYMMDDHHmmssSSS
        try:
            time_formatted = (
                f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]} "
                f"{time_str[8:10]}:{time_str[10:12]}:{time_str[12:14]}"
            )
            trade_time_local = pd.to_datetime(time_formatted)
        except Exception:
            LOGGER.warning("skip invalid time: %s", time_str)
            continue

        trade_time_utc = trade_time_local.tz_localize("Asia/Shanghai").tz_convert("UTC")

        result_rows.append({
            "ts_code": ts_code,
            "trade_time": trade_time_utc,
            "trade_date": trade_date_str,
            "open_price": round_price(open_p),
            "high_price": round_price(high_p),
            "low_price": round_price(low_p),
            "close_price": round_price(close_p),
            "vol": int(vol),
            "amount": round_price(amount),
            "source_name": "baostock_5min",
        })

    return pd.DataFrame(result_rows)


# ─── AKShare 日线降级 ──────────────────────────────────────────────

def fetch_akshare_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过 AKShare 获取日线数据。"""
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="",
    )
    return df


def synthesize_minute_from_daily(daily_df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """从日线数据合成伪分钟线（精度较低但可用）。"""
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()

    result_rows = []
    for _, row in daily_df.iterrows():
        d = str(row["日期"])
        trade_date = pd.to_datetime(d).date()
        open_p = float(row["开盘"])
        high_p = float(row["最高"])
        low_p = float(row["最低"])
        close_p = float(row["收盘"])
        vol = float(row["成交量"]) * 100  # 手 -> 股
        amount = float(row.get("成交额", 0))

        if open_p <= 0:
            continue

        am_times = pd.date_range(f"{trade_date} 09:30:00", periods=120, freq="min", tz="Asia/Shanghai")
        pm_times = pd.date_range(f"{trade_date} 13:00:00", periods=120, freq="min", tz="Asia/Shanghai")
        minute_times = list(am_times) + list(pm_times)
        points = len(minute_times)

        vol_per_min = vol // points
        amt_per_min = amount / points

        prev_close = open_p
        for idx, ts_local in enumerate(minute_times):
            frac = (idx + 1) / points
            target = open_p + (close_p - open_p) * frac
            open_m = prev_close
            close_m = target
            high_m = max(open_m, close_m)
            low_m = min(open_m, close_m)

            if idx == points // 3:
                high_m = max(high_m, high_p)
            if idx == (points * 2) // 3:
                low_m = min(low_m, low_p)

            result_rows.append({
                "ts_code": ts_code,
                "trade_time": ts_local.tz_convert("UTC"),
                "trade_date": trade_date,
                "open_price": round_price(max(open_m, 0.001)),
                "high_price": round_price(max(high_m, 0.001)),
                "low_price": round_price(max(low_m, 0.001)),
                "close_price": round_price(max(close_m, 0.001)),
                "vol": int(vol_per_min),
                "amount": round_price(amt_per_min),
                "source_name": "akshare_daily_synth",
            })
            prev_close = close_m

    return pd.DataFrame(result_rows)


# ─── 数据库操作 ────────────────────────────────────────────────────

def load_universe(engine, season_id: int) -> list[str]:
    """从 season_universe 读取股票池。"""
    sql = text(
        """
        SELECT ts_code FROM season_universe
        WHERE season_id = :season_id AND is_active = TRUE
        ORDER BY rank_in_theme ASC
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(sql, {"season_id": season_id}).fetchall()
    return [str(r[0]) for r in rows]


def write_minute_bars(engine, df: pd.DataFrame, batch_size: int = 2000) -> int:
    """批量写入 raw_minute_bars 表。"""
    if df.empty:
        return 0

    total = 0
    with engine.begin() as conn:
        for _, row in df.iterrows():
            try:
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
                          :vol, :amount, :source_name
                        )
                        ON CONFLICT (ts_code, trade_time)
                        DO UPDATE SET
                          open_price = EXCLUDED.open_price,
                          high_price = EXCLUDED.high_price,
                          low_price = EXCLUDED.low_price,
                          close_price = EXCLUDED.close_price,
                          vol = EXCLUDED.vol,
                          amount = EXCLUDED.amount,
                          source_name = EXCLUDED.source_name
                        """
                    ),
                    {
                        "ts_code": row["ts_code"],
                        "trade_time": row["trade_time"].to_pydatetime(),
                        "trade_date": row["trade_date"],
                        "open_price": row["open_price"],
                        "high_price": row["high_price"],
                        "low_price": row["low_price"],
                        "close_price": row["close_price"],
                        "vol": int(row["vol"]),
                        "amount": row["amount"],
                        "source_name": row["source_name"],
                    },
                )
                total += 1
            except Exception as exc:
                LOGGER.warning("skip row %s %s: %s", row["ts_code"], row["trade_time"], exc)
    return total


def clear_existing_data(engine, codes: list[str]):
    """清空指定股票的已有 raw_minute_bars 数据。"""
    with engine.begin() as conn:
        for ts_code in codes:
            conn.execute(
                text("DELETE FROM raw_minute_bars WHERE ts_code = :ts_code"),
                {"ts_code": ts_code},
            )
    LOGGER.info("cleared raw_minute_bars for %d stocks", len(codes))


# ─── 主流程 ────────────────────────────────────────────────────────

def run(args):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)

    engine = create_engine(database_url, future=True)
    start_date = args.start_date
    end_date = args.end_date

    # 确定股票列表
    codes: list[str] = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.season_id:
        codes = load_universe(engine, args.season_id)
        LOGGER.info("loaded %d stocks from season_universe (season_id=%d)", len(codes), args.season_id)
    else:
        print("ERROR: --season-id or --codes is required")
        sys.exit(1)

    if not codes:
        print("ERROR: no stocks to process")
        sys.exit(1)

    use_source = args.source

    # Dry run
    if args.dry_run:
        print(f"Source: {use_source}")
        print(f"Stocks: {len(codes)} from {start_date} to {end_date}")
        for c in codes:
            if use_source == "baostock":
                print(f"  {c} -> {ts_code_to_baostock(c)}")
            else:
                print(f"  {c} -> {ts_code_to_akshare(c)}")
        return

    # 清空已有数据
    if args.overwrite:
        clear_existing_data(engine, codes)

    # BaoStock 登录（如果用 BaoStock）
    if use_source == "baostock":
        if not HAS_BAOSTOCK:
            print("ERROR: baostock not installed. Run: pip install baostock")
            sys.exit(1)
        lg = bs.login()
        if lg.error_code != "0":
            print(f"ERROR: baostock login failed: {lg.error_msg}")
            sys.exit(1)
        LOGGER.info("baostock login success")

    total_rows = 0
    failed_codes: list[str] = []
    start_time = pytime.time()

    for idx, ts_code in enumerate(codes, start=1):
        LOGGER.info("[%d/%d] fetching %s ...", idx, len(codes), ts_code)

        try:
            if use_source == "baostock":
                bs_code = ts_code_to_baostock(ts_code)
                df = fetch_baostock_5min(bs_code, start_date, end_date)
                normalized = normalize_baostock_5min(df, ts_code)

                if normalized.empty:
                    LOGGER.warning("no 5min bars from baostock for %s, skipping", ts_code)
                    failed_codes.append(ts_code)
                    continue

            elif use_source == "akshare-daily":
                if not HAS_AKSHARE:
                    print("ERROR: akshare not installed. Run: pip install akshare")
                    sys.exit(1)

                symbol = ts_code_to_akshare(ts_code)
                daily_df = fetch_akshare_daily(symbol, start_date, end_date)
                normalized = synthesize_minute_from_daily(daily_df, ts_code)

                if normalized.empty:
                    LOGGER.warning("no daily data for %s", ts_code)
                    failed_codes.append(ts_code)
                    continue

            else:
                print(f"ERROR: unknown source: {use_source}")
                sys.exit(1)

            count = write_minute_bars(engine, normalized)
            total_rows += count
            LOGGER.info("  -> %d rows (%s)", count, normalized.iloc[0]["source_name"])

        except Exception as exc:
            LOGGER.error("FAILED %s: %s", ts_code, exc)
            failed_codes.append(ts_code)

        # 请求间隔
        if idx < len(codes):
            pytime.sleep(args.delay)

    # BaoStock 登出
    if use_source == "baostock":
        bs.logout()

    elapsed = pytime.time() - start_time

    # 汇总
    LOGGER.info("=" * 60)
    LOGGER.info("DONE: %d rows for %d stocks in %.1f seconds", total_rows, len(codes) - len(failed_codes), elapsed)
    if failed_codes:
        LOGGER.warning("FAILED (%d): %s", len(failed_codes), ", ".join(failed_codes))
    LOGGER.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="免费 A 股分钟级行情导入（BaoStock / AKShare）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # BaoStock 5分钟线（推荐，全历史免费）
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31

  # 指定股票
  python scripts/etl/akshare_pipeline.py --start-date 2025-12-01 --end-date 2025-12-31 --codes 000547.SZ,002792.SZ

  # AKShare 日线降级（精度低）
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --source akshare-daily

  # 预览
  python scripts/etl/akshare_pipeline.py --season-id 39 --start-date 2025-12-01 --end-date 2025-12-31 --dry-run
        """,
    )
    parser.add_argument("--season-id", type=int, help="赛季 ID（从 season_universe 读取股票池）")
    parser.add_argument("--codes", type=str, help="股票代码列表，逗号分隔（如 000547.SZ,002792.SZ）")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--source",
        type=str,
        default="baostock",
        choices=["baostock", "akshare-daily"],
        help="数据源（默认 baostock，推荐）",
    )
    parser.add_argument("--delay", type=float, default=0.3, help="每只股票之间请求间隔秒数（默认 0.3）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不实际拉取")
    parser.add_argument("--overwrite", action="store_true", help="先清空已有数据")

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
