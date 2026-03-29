import pathlib
import tempfile
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.engine.state import Quote, Tick
from scripts.service.season_scheduler import SeasonScheduler


class _FakeTradingService:
    def __init__(self):
        self.calls: list[int] = []

    def process_tick(self, tick: Tick, quotes_by_code: dict[str, Quote]) -> dict:
        self.calls.append(tick.id)
        return {"tickId": tick.id, "tradeIds": [], "tradeCount": 0}


class TestSeasonScheduler(unittest.TestCase):
    def _tick(self, tick_id: int, minute_of_day: int, matching: bool) -> Tick:
        return Tick(
            id=tick_id,
            season_id=1,
            game_day_no=1,
            minute_of_day=minute_of_day,
            phase="am_continuous",
            matching_mode="batch_match" if matching else "accept_only",
            is_tradable=True,
            is_matching_point=matching,
        )

    def test_scheduler_processes_matching_ticks_only(self):
        fake_service = _FakeTradingService()
        ticks = [
            self._tick(1, 7, False),
            self._tick(2, 8, True),
            self._tick(3, 9, False),
        ]

        def tick_loader(season_id: int, after_tick_id: int):
            return [tick for tick in ticks if tick.id > after_tick_id]

        def quote_loader(season_id: int, tick: Tick):
            return {
                "600000.SH": Quote(
                    ts_code="600000.SH",
                    ref_price=10.0,
                    upper_limit_price=11.0,
                    lower_limit_price=9.0,
                    is_halted=False,
                )
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_file = pathlib.Path(temp_dir) / "scheduler-checkpoint.json"
            scheduler = SeasonScheduler(
                trading_service=fake_service,
                tick_loader=tick_loader,
                quote_loader=quote_loader,
                checkpoint_file=str(checkpoint_file),
            )

            processed = scheduler.run_once(season_id=1)
            self.assertEqual(processed["processed_ticks"], 3)
            self.assertEqual(processed["matching_ticks"], 1)
            self.assertEqual(processed["last_tick_id"], 3)
            self.assertEqual(fake_service.calls, [2])

            processed_again = scheduler.run_once(season_id=1)
            self.assertEqual(processed_again["processed_ticks"], 0)
            self.assertEqual(processed_again["matching_ticks"], 0)


if __name__ == "__main__":
    unittest.main()
