"""Validation tool for compression timeline logic.

Run local synthetic check:
  python scripts/etl/validate_compression.py --mode local

Run database season check:
  python scripts/etl/validate_compression.py --mode db --season-id 1

Output JSON report:
  python scripts/etl/validate_compression.py --mode db --season-id 1 --report-out docs/reports/validation-season-1.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from tushare_pipeline import MATCHING_MINUTES, build_quote_timeline


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors

    def print_report(self):
        print("Validation report")
        print(f"- Errors: {len(self.errors)}")
        print(f"- Warnings: {len(self.warnings)}")

        for idx, msg in enumerate(self.errors, start=1):
            print(f"ERROR {idx}: {msg}")
        for idx, msg in enumerate(self.warnings, start=1):
            print(f"WARN  {idx}: {msg}")


def parse_args():
    parser = argparse.ArgumentParser(description="Compression validator")
    parser.add_argument("--mode", choices=["local", "db"], default="local")
    parser.add_argument("--season-id", type=int, help="required when --mode db")
    parser.add_argument("--report-out", help="optional path to write JSON validation report")
    return parser.parse_args()


def make_sample_day() -> pd.DataFrame:
    rows = []

    am_times = pd.date_range("2026-01-05 09:30:00+08:00", periods=120, freq="min")
    pm_times = pd.date_range("2026-01-05 13:00:00+08:00", periods=120, freq="min")

    price = 10.0
    for ts in list(am_times) + list(pm_times):
        drift = 0.0015
        open_p = price
        close_p = price * (1 + drift)
        high_p = max(open_p, close_p) * 1.001
        low_p = min(open_p, close_p) * 0.999
        rows.append(
            {
                "trade_time": ts.tz_convert("UTC"),
                "open_price": open_p,
                "high_price": high_p,
                "low_price": low_p,
                "close_price": close_p,
                "vol": 10000,
                "amount": 10000 * ((open_p + close_p) / 2),
            }
        )
        price = close_p

    return pd.DataFrame(rows)


def validate_local() -> ValidationResult:
    result = ValidationResult()
    day_df = make_sample_day()
    timeline = build_quote_timeline(day_df=day_df, prev_close=9.8, halted=False)

    if len(timeline) != 60:
        result.errors.append(f"expected 60 minutes, got {len(timeline)}")

    for minute in range(1, 61):
        quote = timeline[minute]

        if quote["upper_limit_price"] <= quote["lower_limit_price"]:
            result.errors.append(f"minute={minute} has invalid price band")
        if quote["ref_price"] < quote["lower_limit_price"] or quote["ref_price"] > quote["upper_limit_price"]:
            result.errors.append(f"minute={minute} ref_price out of band")

        if minute in MATCHING_MINUTES:
            if quote["volume"] < 0:
                result.errors.append(f"minute={minute} has negative volume")
        elif quote["volume"] != 0:
            result.errors.append(f"minute={minute} should have zero volume in non-matching minute")

    print(f"Open auction hint levels: {[timeline[m]['auction_hint_level'] for m in (1, 2, 3)]}")
    print(f"Close auction hint levels: {[timeline[m]['auction_hint_level'] for m in (58, 59, 60)]}")
    return result


def validate_db(season_id: int) -> ValidationResult:
    if not season_id:
        raise ValueError("--season-id is required when --mode db")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for --mode db")

    result = ValidationResult()
    engine = create_engine(database_url, future=True)

    with engine.begin() as conn:
        universe_size = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM season_universe
                WHERE season_id = :season_id
                  AND is_active = TRUE
                """
            ),
            {"season_id": season_id},
        ).scalar_one()

        if universe_size == 0:
            result.errors.append(f"season_id={season_id} has empty active universe")
            return result

        tick_rows = conn.execute(
            text(
                """
                SELECT game_day_no, minute_of_day
                FROM market_ticks
                WHERE season_id = :season_id
                ORDER BY game_day_no, minute_of_day
                """
            ),
            {"season_id": season_id},
        ).fetchall()

        if not tick_rows:
            result.errors.append(f"season_id={season_id} has no market_ticks")
            return result

        minutes_by_day: dict[int, set[int]] = defaultdict(set)
        for row in tick_rows:
            minutes_by_day[int(row[0])].add(int(row[1]))

        expected_minutes = set(range(1, 61))
        for game_day_no, minutes in minutes_by_day.items():
            missing = sorted(expected_minutes - minutes)
            if missing:
                result.errors.append(
                    f"game_day_no={game_day_no} missing minutes: {','.join(str(m) for m in missing[:10])}"
                )

        quote_rows = conn.execute(
            text(
                """
                SELECT
                  mt.game_day_no,
                  mt.minute_of_day,
                  COUNT(mq.id) AS quote_count,
                  SUM(CASE WHEN mq.volume > 0 THEN 1 ELSE 0 END) AS positive_volume_codes,
                  SUM(CASE WHEN mq.ref_price < mq.lower_limit_price OR mq.ref_price > mq.upper_limit_price THEN 1 ELSE 0 END) AS out_of_band_codes,
                  SUM(CASE WHEN mq.upper_limit_price <= mq.lower_limit_price THEN 1 ELSE 0 END) AS bad_band_codes,
                  SUM(CASE WHEN mq.is_halted AND mq.volume > 0 THEN 1 ELSE 0 END) AS halted_volume_codes
                FROM market_ticks mt
                LEFT JOIN market_tick_quotes mq ON mq.tick_id = mt.id
                WHERE mt.season_id = :season_id
                GROUP BY mt.game_day_no, mt.minute_of_day
                ORDER BY mt.game_day_no, mt.minute_of_day
                """
            ),
            {"season_id": season_id},
        ).fetchall()

        if not quote_rows:
            result.errors.append(f"season_id={season_id} has no market_tick_quotes")
            return result

        for row in quote_rows:
            game_day_no = int(row[0])
            minute = int(row[1])
            quote_count = int(row[2] or 0)
            positive_volume_codes = int(row[3] or 0)
            out_of_band_codes = int(row[4] or 0)
            bad_band_codes = int(row[5] or 0)
            halted_volume_codes = int(row[6] or 0)

            if quote_count != universe_size:
                result.errors.append(
                    f"day={game_day_no} minute={minute} quote_count={quote_count} expected={universe_size}"
                )
            if minute not in MATCHING_MINUTES and positive_volume_codes > 0:
                result.errors.append(
                    f"day={game_day_no} minute={minute} has {positive_volume_codes} non-zero volumes in non-matching minute"
                )
            if out_of_band_codes > 0:
                result.errors.append(
                    f"day={game_day_no} minute={minute} has {out_of_band_codes} quotes with ref_price out of limit"
                )
            if bad_band_codes > 0:
                result.errors.append(
                    f"day={game_day_no} minute={minute} has {bad_band_codes} quotes with invalid price band"
                )
            if halted_volume_codes > 0:
                result.errors.append(
                    f"day={game_day_no} minute={minute} has {halted_volume_codes} halted quotes with positive volume"
                )

        total_ticks = len(tick_rows)
        expected_ticks = len(minutes_by_day) * 60
        if total_ticks != expected_ticks:
            result.errors.append(f"tick_count={total_ticks} expected={expected_ticks}")

    return result


def build_report_dict(result: ValidationResult, mode: str, season_id: int | None) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "season_id": season_id,
        "ok": result.ok(),
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "errors": result.errors,
        "warnings": result.warnings,
    }


def write_report(report: dict, report_out: str):
    path = Path(report_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Validation report written: {path}")


def main():
    args = parse_args()

    if args.mode == "local":
        result = validate_local()
    else:
        result = validate_db(args.season_id)

    result.print_report()
    report = build_report_dict(result, mode=args.mode, season_id=args.season_id)

    if args.report_out:
        write_report(report, args.report_out)

    if result.ok():
        print("Compression validation passed")
        return 0

    print("Compression validation failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
