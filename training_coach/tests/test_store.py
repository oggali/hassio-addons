"""Tests for DuckDB coaching facts store."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from classify import EASY_RUN, INTERVALS, STRENGTH, Session  # noqa: E402
from features import Recovery  # noqa: E402
from planner import Plan  # noqa: E402
from recipes import Recipe  # noqa: E402
from settings import Settings  # noqa: E402
from store import CoachStore, session_key  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "coach.duckdb")
        self.store = CoachStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_and_load_sessions(self) -> None:
        sessions = [
            Session(
                session_type=INTERVALS,
                title="Track intervals",
                sport="Run",
                when=date(2026, 9, 10),
                duration_min=45,
                distance_m=8000,
                activity_id="111",
                splits=[{"distance_m": 1000, "pace_min_km": 4.0}],
                source="strava",
            ),
            Session(
                session_type=STRENGTH,
                title="Gym",
                sport="WeightTraining",
                when=date(2026, 9, 9),
                duration_min=50,
                source="strava",
            ),
        ]
        self.assertEqual(self.store.upsert_sessions(sessions), 2)
        loaded = self.store.load_sessions()
        self.assertEqual(len(loaded), 2)
        by_title = {s.title: s for s in loaded}
        self.assertEqual(by_title["Track intervals"].session_type, INTERVALS)
        self.assertEqual(by_title["Track intervals"].activity_id, "111")
        self.assertEqual(by_title["Track intervals"].splits[0]["pace_min_km"], 4.0)
        self.assertEqual(session_key(by_title["Gym"]), "title:Gym|2026-09-09")

    def test_load_sessions_since(self) -> None:
        self.store.upsert_sessions(
            [
                Session(EASY_RUN, "Old", "Run", date(2026, 1, 1), source="history"),
                Session(EASY_RUN, "New", "Run", date(2026, 9, 1), source="strava"),
            ]
        )
        loaded = self.store.load_sessions(since=date(2026, 8, 1))
        self.assertEqual([s.title for s in loaded], ["New"])

    def test_needs_history_seed_and_wipe(self) -> None:
        self.assertTrue(self.store.needs_history_seed())
        self.store.upsert_sessions(
            [Session(EASY_RUN, "Run", "Run", date(2026, 9, 1), activity_id="1")]
        )
        self.assertTrue(self.store.needs_history_seed())  # still missing seed meta
        self.store.mark_history_seeded()
        self.assertFalse(self.store.needs_history_seed())
        self.assertEqual(self.store.session_count(), 1)

        self.store.wipe()
        self.assertEqual(self.store.session_count(), 0)
        self.assertTrue(self.store.needs_history_seed())
        self.assertIsNone(self.store.get_meta("last_history_seed_at"))

    def test_upsert_recovery_and_decision(self) -> None:
        recovery = Recovery(
            band="good",
            rest_mode=False,
            oura_readiness=82,
            oura_sleep=80,
            oura_hrv=45,
            oura_hrv_balance=85,
            oura_temp=0.1,
            garmin_readiness=78,
            garmin_readiness_text=None,
            garmin_body_battery=72,
            garmin_recovery_hours=None,
            garmin_hrv_status=None,
            garmin_hrv_ratio=1.05,
            reasons=["recovery band is good"],
        )
        day = date(2026, 9, 11)
        self.store.upsert_recovery(
            day, recovery, oura_synced_today=True, already_trained_today=False
        )
        plan = Plan(
            session_type=EASY_RUN,
            recipe=Recipe(EASY_RUN, "Easy run (40 min)", "Easy pace", 40),
            why="Recovery is good",
            recovery_band="good",
            yesterday=STRENGTH,
            week_counts={"easy": 1, "strength": 1},
            oura_synced_today=True,
        )
        settings = Settings(timezone="Europe/Helsinki")
        sessions = [
            Session(STRENGTH, "Gym", "WeightTraining", date(2026, 9, 10)),
            Session(EASY_RUN, "Easy", "Run", date(2026, 9, 8), activity_id="9"),
        ]
        self.store.upsert_decision(day, plan, settings, sessions, extra={"k": 1})
        row = self.store._conn.execute(
            "SELECT session_type, title, why FROM decisions WHERE day = ?", [day]
        ).fetchone()
        self.assertEqual(row[0], EASY_RUN)
        self.assertEqual(row[1], "Easy run (40 min)")
        self.assertIn("good", row[2])
        rec = self.store._conn.execute(
            "SELECT band, oura_readiness FROM recovery_daily WHERE day = ?", [day]
        ).fetchone()
        self.assertEqual(rec[0], "good")
        self.assertEqual(rec[1], 82)


if __name__ == "__main__":
    unittest.main()
