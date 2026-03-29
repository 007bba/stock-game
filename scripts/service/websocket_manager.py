from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(frozen=True)
class ConnectionInfo:
    season_id: int
    user_id: str


class ConnectionManager:
    def __init__(self):
        self._season_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._connection_info: dict[WebSocket, ConnectionInfo] = {}
        self._lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket, season_id: int, user_id: str):
        await websocket.accept()
        self._event_loop = asyncio.get_running_loop()
        async with self._lock:
            self._season_connections[season_id].add(websocket)
            self._connection_info[websocket] = ConnectionInfo(season_id=season_id, user_id=user_id)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            info = self._connection_info.pop(websocket, None)
            if info is None:
                return

            season_connections = self._season_connections.get(info.season_id)
            if season_connections is None:
                return

            season_connections.discard(websocket)
            if not season_connections:
                self._season_connections.pop(info.season_id, None)

    async def broadcast_to_season(self, season_id: int, message: dict[str, Any]):
        recipients = await self._season_snapshot(season_id)
        await self._send_json_many(recipients=recipients, message=message)

    async def send_to_user(self, user_id: str, message: dict[str, Any], season_id: int | None = None):
        recipients = await self._user_snapshot(user_id=user_id, season_id=season_id)
        await self._send_json_many(recipients=recipients, message=message)

    def connection_count(self, season_id: int | None = None) -> int:
        if season_id is None:
            return len(self._connection_info)

        season_connections = self._season_connections.get(season_id)
        if season_connections is None:
            return 0
        return len(season_connections)

    def get_event_loop(self) -> asyncio.AbstractEventLoop | None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return None
        return loop

    async def _season_snapshot(self, season_id: int) -> list[WebSocket]:
        async with self._lock:
            return list(self._season_connections.get(season_id, set()))

    async def _user_snapshot(self, user_id: str, season_id: int | None = None) -> list[WebSocket]:
        async with self._lock:
            result: list[WebSocket] = []
            for websocket, info in self._connection_info.items():
                if info.user_id != user_id:
                    continue
                if season_id is not None and info.season_id != season_id:
                    continue
                result.append(websocket)
            return result

    async def _send_json_many(self, recipients: list[WebSocket], message: dict[str, Any]):
        stale_connections: list[WebSocket] = []

        for websocket in recipients:
            try:
                await websocket.send_json(message)
            except Exception:
                stale_connections.append(websocket)

        for websocket in stale_connections:
            await self.disconnect(websocket)
