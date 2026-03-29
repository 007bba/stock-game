# ETL Pipeline Scaffold

This folder contains a runnable scaffold for importing Tushare data and building compressed replay ticks.

## Files

- `tushare_pipeline.py`: CLI pipeline script
- `requirements.txt`: Python dependencies
- `validate_compression.py`: local + database compression validation tool

## Quick Start

```bash
pip install -r scripts/etl/requirements.txt
set TUSHARE_TOKEN=your_token
set DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/stock_game
python scripts/etl/tushare_pipeline.py --mode all --season-id 1 --start-date 2026-01-01 --end-date 2026-01-31
```

PowerShell convenience (auto-load `.env` in current session):

```powershell
.\scripts\load_env.ps1
```

## Modes

- `calendar`: sync trading calendar
- `bars`: sync minute bars (tries `stk_mins`, then `pro_bar`, then `daily -> pseudo minute` fallback)
- `halts`: sync suspend/resume records (`suspend_d`)
- `actions`: sync adjustment/corporate actions (`adj_factor` with retry + full-history fallback)
- `compress`: generate 60-minute timeline and compressed tick records
- `validate`: run database quality checks for a season (`market_ticks` + `market_tick_quotes`)
- `all`: run all steps in order, including `validate`

## Validation

Local timeline check:

```bash
python scripts/etl/validate_compression.py --mode local
```

Database season check:

```bash
set DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/stock_game
python scripts/etl/validate_compression.py --mode db --season-id 1
```

## Validation Report

When running `--mode validate` or `--mode all`, a JSON report is written to:

- `docs/reports/validation-season-<season_id>.json`

## Testing

Run ETL unit tests:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Run DB integration fixture test (requires `DATABASE_URL`):

```bash
set RUN_DB_INTEGRATION=1
python -m unittest tests.etl.test_db_fixture_integration -v
```

Run DB replay integration flow for trading service (requires `DATABASE_URL`):

```bash
set RUN_DB_INTEGRATION=1
python -m unittest tests.integration.test_trade_replay_db_flow -v
```

Fill `market_ticks` for SeasonScheduler (transactional upsert):

```bash
python scripts/service/fill_market_ticks.py --season-id 1 --start-date 2026-01-01 --end-date 2026-01-31
```

## Trading Service Modules (P5)

- `scripts/service/trading_service.py`: service facade over matching engine
- `scripts/service/api.py`: minimal REST adapter for order endpoints
- `scripts/service/season_scheduler.py`: tick scheduler and checkpointing
- `scripts/service/events.py`: sequenced event bus for replay audit

## CI

- Workflow: `.github/workflows/etl-tests.yml`
- `unit-tests`: push/PR 自动运行单测
- `integration-fixture`: 定时或手动触发运行 DB fixture 集成测试（需配置 `DATABASE_URL` secret）

## Important

- Minute endpoint availability depends on your Tushare entitlement; when minute APIs are blocked, pipeline falls back to `daily -> pseudo minute` synthesis.
- Halt endpoint availability depends on whether your account can call `suspend_d`.
- Action sync retries transient/rate-limit errors and falls back to full-history `adj_factor` query when range query fails.
- Replace/extend `fetch_minute_bars` if your account exposes a different minute interface.
- Compression logic follows `docs/specs/tushare-etl-compression.md`.
