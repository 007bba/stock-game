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
    parser = argparse.ArgumentParser(description="Insert season universe stocks")
    parser.add_argument("--season-id", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stocks = [
        ("600000.SH", "leader", "bank"),
        ("600009.SH", "leader", "airport"),
        ("600015.SH", "follower", "bank"),
        ("600016.SH", "follower", "bank"),
        ("600019.SH", "leader", "steel"),
        ("600028.SH", "leader", "energy"),
        ("600030.SH", "leader", "securities"),
        ("600031.SH", "trend", "machinery"),
        ("600036.SH", "leader", "bank"),
        ("600050.SH", "trend", "telecom"),
    ]

    conn = psycopg2.connect(get_db_url())
    try:
        # Keep all writes in a single transaction.
        with conn:
            with conn.cursor() as cur:
                for ts_code, role, event_tag in stocks:
                    cur.execute(
                        """
                        INSERT INTO season_universe (season_id, ts_code, role, event_tag, rank_in_theme, is_active)
                        VALUES (%s, %s, %s, %s, 1, TRUE)
                        ON CONFLICT (season_id, ts_code) DO NOTHING
                        """,
                        (args.season_id, ts_code, role, event_tag),
                    )

                cur.execute("SELECT COUNT(*) FROM season_universe WHERE season_id = %s", (args.season_id,))
                total = cur.fetchone()[0]
                print(f"season_universe(season_id={args.season_id}): {total} stocks")
        print("Done")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise
