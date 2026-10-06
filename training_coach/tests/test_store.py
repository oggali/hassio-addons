"""Tests for DuckDB coaching facts store."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

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
        from datetime import datetime, timezone

        started = datetime(2026, 9, 10, 7, 5, tzinfo=timezone.utc)
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
                started_at=started,
                relative_effort=68.0,
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
        self.assertEqual(by_title["Track intervals"].started_at, started)
        self.assertEqual(by_title["Track intervals"].relative_effort, 68.0)
        self.assertAlmostEqual(by_title["Track intervals"].session_load, 45 * 0.95)
        self.assertAlmostEqual(by_title["Gym"].session_load, 50 * 0.4)
        # Banister traceback: gym day 1, intervals day 2 (overnight decay, then hard load).
        self.assertIsNotNone(by_title["Gym"].ctl_before)
        self.assertIsNotNone(by_title["Gym"].ctl_after)
        self.assertGreater(by_title["Gym"].ctl_after, by_title["Gym"].ctl_before)
        self.assertLess(
            by_title["Track intervals"].ctl_before, by_title["Gym"].ctl_after
        )
        self.assertGreater(
            by_title["Track intervals"].ctl_after,
            by_title["Track intervals"].ctl_before,
        )
        self.assertAlmostEqual(
            by_title["Track intervals"].tsb_after,
            by_title["Track intervals"].ctl_after - by_title["Track intervals"].atl_after,
        )
        self.assertEqual(session_key(by_title["Gym"]), "title:Gym|2026-09-09")

    def test_captured_at_is_kept_when_session_is_rewritten(self) -> None:
        session = Session(
            EASY_RUN, "Easy", "Run", date(2026, 9, 12), activity_id="42", source="strava"
        )
        self.store.upsert_sessions([session])
        captured = self.store._conn.execute(
            "SELECT captured_at FROM sessions WHERE activity_id = '42'"
        ).fetchone()[0]
        self.assertIsNotNone(captured)
        session.title = "Easy later"
        session.duration_min = 50
        self.store.upsert_sessions([session])
        row = self.store._conn.execute(
            "SELECT title, captured_at FROM sessions WHERE activity_id = '42'"
        ).fetchone()
        self.assertEqual(row[0], "Easy later")
        self.assertEqual(row[1], captured)

    def test_session_banister_marginal_impact(self) -> None:
        """Same-day sessions each move CTL; later one starts from earlier one's after."""
        from datetime import datetime, timezone

        from load import CTL_TAU, annotate_session_banister, session_load

        morning = Session(
            INTERVALS,
            "AM",
            "Run",
            date(2026, 9, 10),
            duration_min=40,
            started_at=datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc),
        )
        evening = Session(
            EASY_RUN,
            "PM",
            "Run",
            date(2026, 9, 10),
            duration_min=30,
            started_at=datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc),
        )
        annotate_session_banister([evening, morning])  # input order should not matter
        self.assertEqual(morning.ctl_before, 0.0)
        am_load = session_load(morning)
        self.assertAlmostEqual(morning.ctl_after, am_load / CTL_TAU)
        self.assertAlmostEqual(evening.ctl_before, morning.ctl_after)
        self.assertGreater(evening.ctl_after, evening.ctl_before)
        self.assertIsNotNone(evening.atl_after)
        self.assertIsNotNone(evening.tsb_after)
    def test_upsert_load_daily(self) -> None:
        from load import LoadSnapshot

        day = date(2026, 9, 12)
        snap = LoadSnapshot(
            ctl=40.0,
            atl=55.0,
            tsb=-15.0,
            weekly_km=42.0,
            easy_km=8.0,
            long_km=16.0,
            weekly_load=210.0,
            daily_load=42.75,
        )
        self.store.upsert_load_daily(day, snap)
        row = self.store.get_load_daily(day)
        self.assertIsNotNone(row)
        self.assertEqual(row["ctl"], 40.0)
        self.assertEqual(row["atl"], 55.0)
        self.assertEqual(row["tsb"], -15.0)
        self.assertEqual(row["weekly_load"], 210.0)
        self.assertEqual(row["daily_load"], 42.75)
        self.assertEqual(len(self.store.load_load_daily(since=date(2026, 9, 1))), 1)
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

    def test_publish_share_copy_matches_live_rows(self) -> None:
        self.store.upsert_sessions(
            [Session(EASY_RUN, "Easy", "Run", date(2026, 9, 12), activity_id="42", source="strava")]
        )
        self.store.set_meta("schema_version", "2")
        dest = Path(self.tmp.name) / "nested" / "coach.duckdb"
        self.store.publish_share_copy(dest)
        copy = duckdb.connect(str(dest), read_only=True)
        titles = [row[0] for row in copy.execute("SELECT title FROM sessions ORDER BY title").fetchall()]
        self.assertEqual(titles, ["Easy"])
        self.assertEqual(copy.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0], "2")
        copy.close()
        self.store.upsert_sessions(
            [Session(EASY_RUN, "Later", "Run", date(2026, 9, 13), activity_id="43", source="strava")]
        )
        self.store.publish_share_copy(dest)
        fresh = duckdb.connect(str(dest), read_only=True)
        self.addCleanup(fresh.close)
        titles = [row[0] for row in fresh.execute("SELECT title FROM sessions ORDER BY title").fetchall()]
        self.assertEqual(titles, ["Easy", "Later"])


if __name__ == "__main__":
    unittest.main()
