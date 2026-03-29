import os
import sys

import psycopg2


def get_db_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required")
    return db_url


def main() -> int:
    conn = psycopg2.connect(get_db_url())

    try:
        # Keep all writes in a single transaction.
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, season_code FROM seasons ORDER BY id LIMIT 1")
                existing = cur.fetchone()
                if existing:
                    print(f"Season already exists: id={existing[0]}, season_code={existing[1]}")
                    return 0

                cur.execute(
                    """
                    INSERT INTO seasons (season_code, season_name, status, total_game_days, day_minutes, start_at, end_at)
                    VALUES ('2026-S1', '2026 Season', 'running', 120, 60, '2026-01-01', '2026-06-30')
                    RETURNING id, season_code
                    """
                )
                row = cur.fetchone()
                print(f"Season created: id={row[0]}, season_code={row[1]}")
                return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise
