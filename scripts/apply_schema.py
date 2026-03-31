from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
SCHEMA_PATH = ROOT / 'db' / 'schema.sql'

_VALID_SCHEMES = ('postgresql://', 'postgres://')
_MAX_RETRIES = 5
_BACKOFF_BASE = 2  # seconds


def _mask_url(url: str) -> str:
    """Return the URL with the password replaced by '***' for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.password:
            # Rebuild netloc with masked password
            netloc = parsed.hostname or ''
            if parsed.port:
                netloc = f'{netloc}:{parsed.port}'
            netloc = f'{parsed.username}:***@{netloc}'
            masked = parsed._replace(netloc=netloc)
            return urlunparse(masked)
    except Exception:
        pass
    return url[:20] + '...' if len(url) > 20 else url


def get_db_url() -> str:
    """Read and validate DATABASE_URL from the environment."""
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        raise RuntimeError(
            'DATABASE_URL environment variable is not set or is empty. '
            'Ensure the variable is injected into the container at runtime.'
        )

    if not any(database_url.startswith(scheme) for scheme in _VALID_SCHEMES):
        raise RuntimeError(
            f'DATABASE_URL has an invalid format. '
            f'Expected a connection string starting with "postgresql://" or "postgres://", '
            f'but got: {_mask_url(database_url)!r}. '
            f'Check that the variable contains a full PostgreSQL DSN, not a bare host or key.'
        )

    return database_url


def apply_schema() -> None:
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f'schema file not found: {SCHEMA_PATH}')

    db_url = get_db_url()
    print(f'[apply_schema] DATABASE_URL={_mask_url(db_url)!r}')

    schema_sql = SCHEMA_PATH.read_text(encoding='utf-8')

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            conn = psycopg2.connect(db_url)
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
            finally:
                conn.close()
            return  # success — exit the retry loop
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** (attempt - 1)  # 1, 2, 4, 8 seconds
                print(
                    f'[apply_schema] Connection attempt {attempt}/{_MAX_RETRIES} failed '
                    f'({exc}). Retrying in {wait}s...'
                )
                time.sleep(wait)
            else:
                print(
                    f'[apply_schema] Connection attempt {attempt}/{_MAX_RETRIES} failed '
                    f'({exc}). No more retries.'
                )

    raise RuntimeError(
        f'Failed to connect to the database after {_MAX_RETRIES} attempts. '
        f'Last error: {last_exc}'
    ) from last_exc


if __name__ == '__main__':
    apply_schema()
    print('[OK] schema applied from db/schema.sql')
