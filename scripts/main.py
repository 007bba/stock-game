"""
Stock Game API Server Entry Point

Usage:
    python scripts/main.py
    # or
    uvicorn scripts.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import logging
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from scripts.engine.pg_state import PgState
from scripts.service.api import create_app
from scripts.service.event_publisher import EventPublisher
from scripts.service.market_session_service import MarketSessionService
from scripts.service.replay_data import ReplayDataService, build_current_quote_provider, build_current_tick_provider
from scripts.service.season_scheduler import SeasonScheduler, build_db_quote_loader, build_db_tick_loader
from scripts.service.trading_service import TradingService
from scripts.service.websocket_manager import ConnectionManager


LOGGER = logging.getLogger(__name__)


def _parse_auto_advance_season_ids(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []

    result: list[int] = []
    for chunk in raw_value.split(','):
        value = chunk.strip()
        if not value:
            continue
        try:
            result.append(int(value))
        except ValueError:
            LOGGER.warning('ignore invalid season id in AUTO_ADVANCE_SEASON_IDS: %s', value)

    return sorted(set(result))


def _tick_to_payload(tick) -> dict:
    return {
        'tickId': tick.id,
        'seasonId': tick.season_id,
        'gameDayNo': tick.game_day_no,
        'minuteOfDay': tick.minute_of_day,
        'phase': tick.phase,
        'matchingMode': tick.matching_mode,
        'isTradable': tick.is_tradable,
        'isMatchingPoint': tick.is_matching_point,
    }


def _build_tick_snapshot(
    replay_data: ReplayDataService,
    season_id: int,
    tick,
    next_tick,
    next_tick_eta_seconds: float,
) -> dict:
    snapshot = _tick_to_payload(tick)
    snapshot['nextTickId'] = next_tick.id if next_tick is not None else None
    snapshot['nextTickAt'] = (
        (datetime.now(timezone.utc) + timedelta(seconds=max(next_tick_eta_seconds, 0))).isoformat()
        if next_tick is not None
        else None
    )
    snapshot['quotes'] = replay_data.list_tick_quotes(season_id=season_id, tick_id=tick.id)
    return snapshot


def _build_snapshot_provider(
    replay_data: ReplayDataService,
    scheduler: SeasonScheduler,
    next_tick_eta_seconds: float,
):
    def _provider(season_id: int):
        current_tick_id = scheduler.get_checkpoint(season_id)
        tick = replay_data.get_current_tick(season_id=season_id, current_tick_id=current_tick_id)
        if tick is None:
            return None

        next_tick = replay_data.get_next_tick(season_id=season_id, after_tick_id=tick.id)
        return _build_tick_snapshot(
            replay_data=replay_data,
            season_id=season_id,
            tick=tick,
            next_tick=next_tick,
            next_tick_eta_seconds=next_tick_eta_seconds,
        )

    return _provider


def _build_advance_provider(
    scheduler: SeasonScheduler,
    replay_data: ReplayDataService,
    event_publisher,
    next_tick_eta_seconds: float,
):
    def _provider(season_id: int):
        result = scheduler.advance_tick(season_id=season_id)
        if not result.get('advanced'):
            return result

        tick_payload = result.get('tick')
        if tick_payload is None:
            return result

        tick = replay_data.get_tick_by_id(season_id=season_id, tick_id=int(tick_payload['tickId']))
        if tick is None:
            return result

        next_tick_payload = result.get('next_tick')
        next_tick = None
        if isinstance(next_tick_payload, dict):
            next_tick_id = next_tick_payload.get('tickId')
            if isinstance(next_tick_id, int):
                next_tick = replay_data.get_tick_by_id(season_id=season_id, tick_id=next_tick_id)

        if next_tick is None:
            next_tick = replay_data.get_next_tick(season_id=season_id, after_tick_id=tick.id)

        snapshot = _build_tick_snapshot(
            replay_data=replay_data,
            season_id=season_id,
            tick=tick,
            next_tick=next_tick,
            next_tick_eta_seconds=next_tick_eta_seconds,
        )
        event_publisher.publish_to_season(season_id=season_id, event='tick_advance', payload=snapshot)

        result['snapshot'] = snapshot
        return result

    return _provider


def create_app_with_deps() -> FastAPI:
    """Create FastAPI app with all dependencies wired up."""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL environment variable is required')

    tick_interval_seconds = float(os.getenv('TICK_ADVANCE_INTERVAL_SECONDS', '60'))
    auto_advance_season_ids = _parse_auto_advance_season_ids(os.getenv('AUTO_ADVANCE_SEASON_IDS'))

    state = PgState(database_url=database_url)
    replay_data = ReplayDataService(database_url=database_url)
    market_session_service = MarketSessionService(database_url=database_url)

    trading_service = TradingService(state=state)
    scheduler = SeasonScheduler(
        trading_service=trading_service,
        tick_loader=build_db_tick_loader(database_url),
        quote_loader=build_db_quote_loader(database_url),
        checkpoint_file=os.getenv('SCHEDULER_CHECKPOINT_FILE', str(ROOT / 'data' / 'scheduler-checkpoint.json')),
    )

    tick_provider = build_current_tick_provider(replay_data=replay_data, checkpoint_provider=scheduler.get_checkpoint)
    quote_provider = build_current_quote_provider(replay_data=replay_data, current_tick_provider=tick_provider)

    ws_manager = ConnectionManager()
    event_publisher = EventPublisher(ws_manager=ws_manager)

    current_tick_snapshot_provider = _build_snapshot_provider(
        replay_data=replay_data,
        scheduler=scheduler,
        next_tick_eta_seconds=tick_interval_seconds,
    )
    advance_tick_provider = _build_advance_provider(
        scheduler=scheduler,
        replay_data=replay_data,
        event_publisher=event_publisher,
        next_tick_eta_seconds=tick_interval_seconds,
    )

    app = create_app(
        trading_service=trading_service,
        tick_provider=tick_provider,
        quote_provider=quote_provider,
        current_tick_snapshot_provider=current_tick_snapshot_provider,
        advance_tick_provider=advance_tick_provider,
        market_session_service=market_session_service,
        ws_manager=ws_manager,
        event_publisher=event_publisher,
    )

    app.state.scheduler = scheduler
    app.state.replay_data = replay_data
    app.state.market_session_service = market_session_service
    app.state.auto_advance_season_ids = auto_advance_season_ids
    app.state.tick_interval_seconds = tick_interval_seconds
    app.state.auto_advance_task = None

    @app.on_event('startup')
    async def _startup_auto_advance():
        if not auto_advance_season_ids:
            return

        async def _loop():
            while True:
                for season_id in auto_advance_season_ids:
                    try:
                        await asyncio.to_thread(advance_tick_provider, season_id)
                    except Exception:
                        LOGGER.exception('auto advance failed for season_id=%s', season_id)
                await asyncio.sleep(max(tick_interval_seconds, 0.1))

        app.state.auto_advance_task = asyncio.create_task(_loop())

    @app.on_event('shutdown')
    async def _shutdown_auto_advance():
        task = app.state.auto_advance_task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    allowed_origins = [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'https://stock-game-4cp.pages.dev',
    ]
    custom_origin = os.getenv('CORS_ORIGIN')
    if custom_origin:
        allowed_origins.append(custom_origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    return app


app = create_app_with_deps()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(
        'scripts.main:app',
        host='0.0.0.0',
        port=8000,
        reload=True,
    )
