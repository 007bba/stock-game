import json
import pathlib
import tempfile
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.service.events import EventBus


class TestEvents(unittest.TestCase):
    def test_emit_trade_and_order_events_with_sequence(self):
        bus = EventBus()

        event_1 = bus.emit_trade_matched({"tradeId": 101, "tickId": 8})
        event_2 = bus.emit_order_updated({"id": 1, "status": "filled"})

        self.assertEqual(event_1["event"], "trade.matched")
        self.assertEqual(event_2["event"], "order.updated")
        self.assertEqual(event_2["sequence"], event_1["sequence"] + 1)
        self.assertIn("serverTime", event_1)

    def test_export_recent_events(self):
        bus = EventBus()
        bus.emit_clock_tick({"tickId": 7})
        bus.emit_trade_matched({"tradeId": 201, "tickId": 8})

        with tempfile.TemporaryDirectory() as temp_dir:
            output = pathlib.Path(temp_dir) / "events.json"
            bus.export_json(str(output), limit=1)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["event"], "trade.matched")


if __name__ == "__main__":
    unittest.main()
