"""Prefs, race-time parsing, and DuckDB prefs history."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from goal import (  # noqa: E402
    Prefs,
    format_hms,
    normalize_race_distance,
    parse_target_seconds,
    phase_for,
)
from prefs import prefs_from_states  # noqa: E402
from store import CoachStore  # noqa: E402


class GoalParseTests(unittest.TestCase):
    def test_target_mmss_and_hms(self):
        self.assertEqual(parse_target_seconds("22:30"), 22 * 60 + 30)
        self.assertEqual(parse_target_seconds("1:45:00"), 1 * 3600 + 45 * 60)
        self.assertEqual(parse_target_seconds("3:15"), 3 * 3600 + 15 * 60)
        self.assertEqual(format_hms(6300), "1:45:00")

    def test_distance_aliases(self):
        self.assertEqual(normalize_race_distance("Half Marathon"), "half")
        self.assertEqual(normalize_race_distance("none"), "none")

    def test_phase(self):
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="half")
        self.assertEqual(phase_for(date(2026, 10, 4), prefs), "race")
        self.assertEqual(phase_for(date(2026, 9, 25), prefs), "taper")


class PrefsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CoachStore(str(Path(self.tmp.name) / "coach.duckdb"))

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_history_close_and_insert(self):
        first = self.store.insert_prefs(Prefs.defaults())
        self.assertIsNotNone(first.prefs_id)
        second = self.store.insert_prefs(
            Prefs(race_date=date(2026, 10, 4), race_distance="half", target_time="1:45:00")
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        current = self.store.current_prefs()
        self.assertEqual(current.race_distance, "half")
        row = self.store._conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN valid_to IS NULL THEN 1 ELSE 0 END) FROM prefs_history"
        ).fetchone()
        self.assertEqual(row[0], 2)
        self.assertEqual(row[1], 1)

    def test_same_fingerprint_is_noop(self):
        a = self.store.insert_prefs(Prefs.defaults())
        b = self.store.insert_prefs(Prefs.defaults())
        self.assertEqual(a.prefs_id, b.prefs_id)

    def test_prefs_from_helper_states(self):
        states = {
            "input_datetime.training_coach_race_date": {"state": "2026-10-04 00:00:00", "attributes": {}},
            "input_select.training_coach_race_distance": {"state": "half", "attributes": {}},
            "input_text.training_coach_target_time": {"state": "1:45:00", "attributes": {}},
            "input_number.training_coach_weekly_long_runs": {"state": "1", "attributes": {}},
            "input_number.training_coach_weekly_quality_runs": {"state": "2", "attributes": {}},
            "input_number.training_coach_weekly_strength": {"state": "2", "attributes": {}},
            "input_number.training_coach_weekly_rest_days": {"state": "1", "attributes": {}},
        }
        prefs = prefs_from_states(states, date(2026, 9, 12))
        self.assertEqual(prefs.race_date, date(2026, 10, 4))
        self.assertEqual(prefs.weekly_quality_runs, 2)
        self.assertEqual(prefs.target_seconds, 6300)


if __name__ == "__main__":
    unittest.main()
