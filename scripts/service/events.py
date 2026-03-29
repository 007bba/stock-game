from __future__ import annotations

import json
from datetime import datetime, timezone


class EventBus:
    def __init__(self, start_sequence: int = 1):
        self._sequence = int(start_sequence)
        self._events: list[dict] = []

    def emit(self, event: str, payload: dict) -> dict:
        envelope = {
            "event": event,
            "sequence": self._sequence,
            "serverTime": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._events.append(envelope)
        self._sequence += 1
        return envelope

    def emit_clock_tick(self, payload: dict) -> dict:
        return self.emit("clock.tick", payload)

    def emit_order_updated(self, payload: dict) -> dict:
        return self.emit("order.updated", payload)

    def emit_trade_matched(self, payload: dict) -> dict:
        return self.emit("trade.matched", payload)

    def emit_leaderboard_updated(self, payload: dict) -> dict:
        return self.emit("leaderboard.updated", payload)

    def latest(self, limit: int = 50) -> list[dict]:
        if limit <= 0:
            return []
        return self._events[-limit:]

    def export_json(self, file_path: str, limit: int = 50):
        payload = self.latest(limit=limit)
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
