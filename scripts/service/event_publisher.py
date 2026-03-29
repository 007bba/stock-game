from __future__ import annotations

import asyncio
from typing import Any

from scripts.service.events import EventBus
from scripts.service.websocket_manager import ConnectionManager


class EventPublisher:
    def __init__(
        self,
        ws_manager: ConnectionManager,
        event_bus: EventBus | None = None,
    ):
        self._ws_manager = ws_manager
        self._event_bus = event_bus or EventBus()

    def publish_to_season(self, season_id: int, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = self._event_bus.emit(event=event, payload=payload)
        self._dispatch_to_season(season_id=season_id, envelope=envelope)
        return envelope

    def publish_to_user(
        self,
        user_id: str,
        event: str,
        payload: dict[str, Any],
        season_id: int | None = None,
    ) -> dict[str, Any]:
        envelope = self._event_bus.emit(event=event, payload=payload)
        self._dispatch_to_user(user_id=user_id, season_id=season_id, envelope=envelope)
        return envelope

    def latest(self, limit: int = 50) -> list[dict]:
        return self._event_bus.latest(limit=limit)

    def _dispatch_to_season(self, season_id: int, envelope: dict[str, Any]):
        self._submit_coroutine(self._ws_manager.broadcast_to_season, season_id, envelope)

    def _dispatch_to_user(self, user_id: str, season_id: int | None, envelope: dict[str, Any]):
        self._submit_coroutine(self._ws_manager.send_to_user, user_id, envelope, season_id)

    def _submit_coroutine(self, async_fn, *args):
        ws_loop = self._ws_manager.get_event_loop()
        if ws_loop is None:
            return

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is ws_loop:
            asyncio.create_task(async_fn(*args))
            return

        asyncio.run_coroutine_threadsafe(async_fn(*args), ws_loop)
