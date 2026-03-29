"""
Seed script: create test users and accounts in Supabase PostgreSQL.

Run once after `db/schema.sql` has been applied.

Usage:
    python -m scripts.init_engine_db
"""

from __future__ import annotations

import os
import uuid

import psycopg2


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set")

    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()

    # ── Test users ───────────────────────────────────────────────────────────
    users = [
        (
            uuid.UUID("a0000000-0000-0000-0000-000000000001"),
            "player1",
            "玩家1",
        ),
        (
            uuid.UUID("a0000000-0000-0000-0000-000000000002"),
            "player2",
            "玩家2",
        ),
    ]

    for user_id, login_name, display_name in users:
        cur.execute(
            """
            INSERT INTO users (id, login_name, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (str(user_id), login_name, display_name),
        )
        print(f"[OK] user {login_name} ({user_id})")

    # ── Season 1 accounts (initial cash 1,000,000 each) ─────────────────────
    # season_id = 1 must exist (run scripts/init_db.py first if needed)
    accounts = [
        (1, uuid.UUID("a0000000-0000-0000-0000-000000000001"), 1_000_000),
        (1, uuid.UUID("a0000000-0000-0000-0000-000000000002"), 1_000_000),
    ]

    for season_id, user_id, initial_cash in accounts:
        cur.execute(
            """
            INSERT INTO accounts
              (season_id, user_id, initial_cash, available_cash, frozen_cash)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT (season_id, user_id) DO NOTHING
            """,
            (season_id, str(user_id), initial_cash, initial_cash),
        )
        print(f"[OK] account  season={season_id} user={user_id} cash={initial_cash}")

    cur.close()
    conn.close()
    print("\nAll seed data inserted successfully.")


if __name__ == "__main__":
    main()
