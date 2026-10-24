"""Tests for Strava km-split classification and history matching."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from classify import EASY_RUN, INTERVALS, TEMPO, Session, classify_logged_session  # noqa: E402
from splits import SplitSet, apply_splits_to_sessions, classify_from_splits, parse_split_entity  # noqa: E402
from entities import STRAVA_LATEST_SPLITS  # noqa: E402
from features import build_snapshot  # noqa: E402
from settings import Settings  # noqa: E402
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
    def test_parse_relative_effort(self):
        ent = entity(
            5,
            SATURDAY,
            activity_id=42,
            activity_name="Easy",
            activity_type="Run",
            distance_m=5000,
            moving_time_s=1800,
            splits_metric=km_splits(5.5, 5.5, 5.5, 5.5, 5.5),
            relative_effort=22,
        )
        parsed = parse_split_entity(ent, TZ)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.relative_effort, 22.0)

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

    def test_reference_max_keeps_steady_run_easy_when_splits_attach(self):
        session = Session(
            TEMPO,
            "Night Run",
            "Run",
            SATURDAY.date(),
            duration_min=60.75,
            avg_hr=148.3,
            max_hr=159,
            activity_id="20692272647",
            distance_m=10270,
        )
        split_set = SplitSet(
            activity_id="20692272647",
            activity_name="Night Run",
            activity_type="Run",
            distance_m=10270,
            moving_time_s=3645,
            splits=km_splits(6.05, 6.00, 6.08, 5.98, 6.02, 6.04, 6.01, 5.99, 6.03, 6.02),
        )
        updated = apply_splits_to_sessions(
            [session], {"20692272647": split_set}, 75, hr_max=195
        )
        self.assertEqual(updated[0].session_type, EASY_RUN)

    def test_stored_interval_splits_survive_reference_reclassify(self):
        session = Session(
            TEMPO,
            "Afternoon run",
            "Run",
            SATURDAY.date(),
            duration_min=40,
            avg_hr=150,
            max_hr=170,
            activity_id="1",
            distance_m=7000,
            splits=km_splits(5.8, 4.3, 5.9, 4.2, 5.8, 4.3, 5.7),
        )
        self.assertEqual(classify_logged_session(session, 75, 195), INTERVALS)


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

    def test_same_title_runs_on_different_days_both_kept(self):
        """Latest splits must not steal the previous Afternoon Run's identity."""
        states = good_recovery()
        older = SATURDAY - timedelta(days=2)
        newer = SATURDAY - timedelta(days=1)
        add_strava(
            states, 0, "Afternoon Run", "Run", newer, 35, avg_hr=160, activity_id=20460937038
        )
        add_strava(
            states, 1, "Afternoon Run", "Run", older, 40, avg_hr=155, activity_id=20447786598
        )
        states[STRAVA_LATEST_SPLITS] = entity(
            7,
            newer,
            activity_id=20460937038,
            activity_name="Afternoon Run",
            activity_type="Run",
            distance_m=6000,
            moving_time_s=2100,
            splits_metric=km_splits(5.8, 4.3, 5.9, 4.2, 5.8, 4.3, 5.7),
            laps=[],
        )
        settings = Settings(timezone="Europe/Helsinki")
        snap = build_snapshot(states, settings, now=SATURDAY)
        by_id = {s.activity_id: s for s in snap.sessions}
        self.assertIn("20460937038", by_id)
        self.assertIn("20447786598", by_id)
        self.assertEqual(by_id["20460937038"].when, newer.date())
        self.assertEqual(by_id["20447786598"].when, older.date())
        self.assertEqual(by_id["20460937038"].session_type, INTERVALS)

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
