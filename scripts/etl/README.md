# ETL Pipeline Scaffold

This folder contains a runnable scaffold for importing Tushare data and building compressed replay ticks.

## Files

- `tushare_pipeline.py`: CLI pipeline script
- `requirements.txt`: Python dependencies

## Quick Start

```bash
pip install -r scripts/etl/requirements.txt
set TUSHARE_TOKEN=your_token
set DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/stock_game
python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-01 --end-date 2026-01-31
```

## Modes

- `calendar`: sync trading calendar
- `bars`: sync minute bars (replace placeholder API call with your entitled interface)
- `actions`: sync adjustment/corporate actions
- `compress`: generate 60-minute timeline and compressed tick records
- `all`: run all steps in order

## Important

- `sync_minute_bars` currently contains a placeholder for minute endpoint call because Tushare account entitlement differs.
- Replace TODO sections according to your enabled interfaces before production use.
- Compression logic should follow `docs/specs/tushare-etl-compression.md`.
