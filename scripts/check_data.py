import argparse
import os
import sys

import psycopg2


def get_db_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required")
    return db_url


def parse_args():
    parser = argparse.ArgumentParser(description="Check ETL data counts")
    parser.add_argument("--season-id", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    conn = psycopg2.connect(get_db_url())
    try:
        with conn.cursor() as cur:
            print(f"Counts for season_id={args.season_id}:")

            cur.execute("SELECT COUNT(*) FROM market_ticks WHERE season_id = %s", (args.season_id,))
            print(f"  market_ticks: {cur.fetchone()[0]}")

            cur.execute("SELECT COUNT(*) FROM market_tick_quotes WHERE season_id = %s", (args.season_id,))
            print(f"  market_tick_quotes: {cur.fetchone()[0]}")

            cur.execute("SELECT COUNT(*) FROM season_universe WHERE season_id = %s", (args.season_id,))
            print(f"  season_universe: {cur.fetchone()[0]}")

            cur.execute("""
                SELECT COUNT(*)
                FROM raw_minute_bars b
                WHERE EXISTS (
                  SELECT 1
                  FROM season_universe u
                  WHERE u.season_id = %s
                    AND u.is_active = TRUE
                    AND u.ts_code = b.ts_code
                )
            """, (args.season_id,))
            print(f"  raw_minute_bars(for universe): {cur.fetchone()[0]}")

            cur.execute(
                "SELECT COUNT(*) FROM etl_jobs WHERE season_id = %s AND status = 'failed'",
                (args.season_id,),
            )
            print(f"  etl_jobs_failed: {cur.fetchone()[0]}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise
