"""Scheduler helpers: fire once per named slot, never 90s early."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from main import (  # noqa: E402
    consume_daily_notify,
    morning_slot_passed,
    next_named_event,
    should_fire_named_event,
)
from settings import Settings  # noqa: E402
from store import CoachStore  # noqa: E402

TZ = ZoneInfo("Europe/Helsinki")
SETTINGS = Settings(timezone="Europe/Helsinki", run_time="07:30", evening_time="20:30")


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 13, hour, minute, second, tzinfo=TZ)


class ScheduleTests(unittest.TestCase):
    def test_does_not_fire_90s_before_morning(self) -> None:
        now = at(7, 28, 31)
        target, kind = next_named_event(now, SETTINGS)
        self.assertEqual(kind, "morning")
        self.assertEqual(target, at(7, 30))
        self.assertFalse(should_fire_named_event(now, target, kind, None))

    def test_fires_at_morning_and_not_again_before_evening(self) -> None:
        target = at(7, 30)
        self.assertTrue(should_fire_named_event(at(7, 30), target, "morning", None))
        last = (date(2026, 9, 13), "morning")
        self.assertFalse(should_fire_named_event(at(7, 30, 45), target, "morning", last))
        self.assertFalse(should_fire_named_event(at(7, 31), target, "morning", last))

    def test_early_morning_fire_would_still_see_todays_slot(self) -> None:
        """Reproduce the old bug: fire ~90s early, cooldown 60s, slot still upcoming."""
        early = at(7, 28, 31)
        target, kind = next_named_event(early, SETTINGS)
        self.assertEqual(kind, "morning")
        after_cooldown = early + timedelta(seconds=60)
        still_morning, still_kind = next_named_event(after_cooldown, SETTINGS)
        self.assertEqual(still_kind, "morning")
        self.assertEqual(still_morning.date(), early.date())
        last = (early.date(), "morning")
        self.assertFalse(
            should_fire_named_event(after_cooldown, still_morning, still_kind, last)
        )

    def test_evening_same_day_is_a_new_slot(self) -> None:
        last = (date(2026, 9, 13), "morning")
        target = at(20, 30)
        self.assertTrue(should_fire_named_event(at(20, 30), target, "evening", last))

    def test_startup_notifies_only_after_morning_slot(self) -> None:
        self.assertFalse(morning_slot_passed(at(7, 0), SETTINGS))
        self.assertTrue(morning_slot_passed(at(7, 30), SETTINGS))
        self.assertTrue(morning_slot_passed(at(8, 0), SETTINGS))

    def test_consume_daily_notify_once(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = CoachStore(str(Path(tmp.name) / "coach.duckdb"))
        self.addCleanup(store.close)
        day = date(2026, 9, 13)
        self.assertTrue(consume_daily_notify(store, day, "morning"))
        self.assertFalse(consume_daily_notify(store, day, "morning"))
        self.assertTrue(consume_daily_notify(store, day, "evening"))
        self.assertTrue(consume_daily_notify(store, date(2026, 9, 14), "morning"))


if __name__ == "__main__":
    unittest.main()
