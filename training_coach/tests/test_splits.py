"""Tests for Strava km-split classification and history matching."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from classify import EASY_RUN, INTERVALS, TEMPO  # noqa: E402
from entities import STRAVA_LATEST_SPLITS  # noqa: E402
from features import build_snapshot  # noqa: E402
from settings import Settings  # noqa: E402
from splits import SplitSet, classify_from_splits  # noqa: E402
from test_planner import SATURDAY, add_strava, entity, good_recovery  # noqa: E402

TZ = ZoneInfo("Europe/Helsinki")


def km_splits(*paces: float) -> list[dict]:
    rows = []
    for i, pace in enumerate(paces, start=1):
        rows.append(
            {
                "split": i,
                "distance_m": 1000,
                "moving_time_s": int(pace * 60),
                "pace_min_km": pace,
                "pace": f"{int(pace)}:{int(round((pace % 1) * 60)):02d}",
            }
        )
    return rows


class SplitClassifyTests(unittest.TestCase):
    def test_intervals_from_alternating_km(self):
        split_set = SplitSet(
            activity_id="1",
            activity_name="Afternoon run",
            activity_type="Run",
            distance_m=7000,
            moving_time_s=2100,
            splits=km_splits(5.8, 4.3, 5.9, 4.2, 5.8, 4.3, 5.7),
        )
        self.assertEqual(classify_from_splits(split_set), INTERVALS)

    def test_tempo_from_steady_block(self):
        split_set = SplitSet(
            activity_id="2",
            activity_name="Lunch run",
            activity_type="Run",
            distance_m=8000,
            moving_time_s=2400,
            splits=km_splits(5.8, 4.60, 4.55, 4.58, 4.62, 4.57, 5.5, 5.6),
        )
        self.assertEqual(classify_from_splits(split_set), TEMPO)

    def test_even_easy_is_not_quality(self):
        split_set = SplitSet(
            activity_id="3",
            activity_name="Easy",
            activity_type="Run",
            distance_m=6000,
            moving_time_s=1980,
            splits=km_splits(5.50, 5.45, 5.52, 5.48, 5.50, 5.47),
        )
        self.assertIsNone(classify_from_splits(split_set))


class SplitHistoryTests(unittest.TestCase):
    def test_generic_title_becomes_intervals_via_live_splits(self):
        states = good_recovery()
        add_strava(
            states,
            0,
            "Afternoon run",
            "Run",
            SATURDAY - timedelta(days=1),
            40,
            avg_hr=145,
        )
        states["sensor.strava_oskari_vuorinen_recent_activity"]["attributes"]["activity_id"] = 99
        states[STRAVA_LATEST_SPLITS] = entity(
            7,
            SATURDAY - timedelta(days=1),
            activity_id=99,
            activity_name="Afternoon run",
            activity_type="Run",
            distance_m=7000,
            moving_time_s=2100,
            splits_metric=km_splits(5.8, 4.3, 5.9, 4.2, 5.8, 4.3, 5.7),
            laps=[],
        )
        settings = Settings(timezone="Europe/Helsinki")
        snap = build_snapshot(states, settings, now=SATURDAY)
        yesterday = [s for s in snap.sessions if s.when == (SATURDAY - timedelta(days=1)).date()]
        self.assertTrue(yesterday)
        self.assertEqual(yesterday[0].session_type, INTERVALS)

    def test_history_adds_older_run_not_in_recent_slots(self):
        states = good_recovery()
        older = SATURDAY - timedelta(days=4)
        history = [
            [
                {
                    "entity_id": STRAVA_LATEST_SPLITS,
                    "state": "8",
                    "last_updated": older.isoformat(),
                    "last_changed": older.isoformat(),
                    "attributes": {
                        "activity_id": 55,
                        "activity_name": "Lunch run",
                        "activity_type": "Run",
                        "distance_m": 8000,
                        "moving_time_s": 2400,
                        "splits_metric": km_splits(5.8, 4.60, 4.55, 4.58, 4.62, 4.57, 5.5, 5.6),
                        "laps": [],
                    },
                }
            ]
        ]
        settings = Settings(timezone="Europe/Helsinki")
        snap = build_snapshot(states, settings, now=SATURDAY, split_history=history)
        types = {s.session_type for s in snap.sessions}
        self.assertIn(TEMPO, types)


if __name__ == "__main__":
    unittest.main()
