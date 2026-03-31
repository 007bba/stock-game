from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
SCHEMA_PATH = ROOT / 'db' / 'schema.sql'


def get_db_url() -> str:
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL is required')
    return database_url


def apply_schema() -> None:
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f'schema file not found: {SCHEMA_PATH}')

    schema_sql = SCHEMA_PATH.read_text(encoding='utf-8')
    conn = psycopg2.connect(get_db_url())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(schema_sql)
    finally:
        conn.close()


if __name__ == '__main__':
    apply_schema()
    print('[OK] schema applied from db/schema.sql')
