"""
Stock Game API Server Entry Point

Usage:
    python scripts/main.py
    # or
    uvicorn scripts.main:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from scripts.engine.pg_state import PgState
from scripts.service.api import create_app
from scripts.service.trading_service import TradingService


def get_tick_provider():
    """Provide tick data for a season (placeholder for now)."""
    def tick_provider(season_id: int):
        from scripts.engine.state import Tick
        # TODO: Load from database
        return Tick(
            id=1,
            season_id=season_id,
            game_day=1,
            tick_index=1,
            is_matching_point=True,
        )
    return tick_provider


def get_quote_provider():
    """Provide quote data for a stock in a season (placeholder for now)."""
    def quote_provider(season_id: int, ts_code: str):
        from scripts.engine.state import Quote
        # TODO: Load from database
        return Quote(
            ts_code=ts_code,
            open=10.0,
            high=10.5,
            low=9.5,
            close=10.2,
            volume=1000000,
        )
    return quote_provider


def create_app_with_deps() -> FastAPI:
    """Create FastAPI app with all dependencies wired up."""
    # Initialize state
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    
    state = PgState(database_url=database_url)
    
    # Create trading service
    trading_service = TradingService(state=state)
    
    # Create providers
    tick_provider = get_tick_provider()
    quote_provider = get_quote_provider()
    
    # Create and return app
    app = create_app(
        trading_service=trading_service,
        tick_provider=tick_provider,
        quote_provider=quote_provider,
    )
    
    # Add CORS middleware for frontend
    # Production domains from environment or defaults
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://stock-game-4cp.pages.dev",
    ]
    # Add custom origin from environment variable (for production)
    custom_origin = os.getenv("CORS_ORIGIN")
    if custom_origin:
        allowed_origins.append(custom_origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return app


# For uvicorn
app = create_app_with_deps()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "scripts.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
