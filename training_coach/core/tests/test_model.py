"""Impulse, pace-at-HR, check-in nudge, fatigue gain, backtest, readiness."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from coach.backtest import backtest_report
from coach.classify import CROSS_EASY, EASY_RUN, LONG_RUN, Session
from coach.goal import Prefs
from coach.load import annotate_session_banister, build_load_snapshot, running_impulse, session_load
from coach.paces import build_paces
from coach.performance import (
    fit_fatigue_gain,
    pace_nudge_min,
    performance_points,
    readiness_factor,
)
from coach.simulate import _projected_form


def _run(day: date, minutes: float, km: float, hr: float | None = None, kind: str = EASY_RUN) -> Session:
    return Session(
        kind,
        "run",
        "Run",
        day,
        duration_min=minutes,
        distance_m=km * 1000,
        avg_hr=hr,
        max_hr=190,
    )


class ImpulseTests(unittest.TestCase):
    def test_fallback_matches_minutes_times_intensity(self):
        easy = Session(EASY_RUN, "easy", "Run", date(2026, 1, 1), duration_min=40)
        self.assertAlmostEqual(session_load(easy), 24.0)

    def test_suffer_score_sets_the_impulse(self):
        easy = Session(
            EASY_RUN, "easy", "Run", date(2026, 1, 1), duration_min=40, relative_effort=24
        )
        hard = Session(
            EASY_RUN, "easy", "Run", date(2026, 1, 1), duration_min=40, relative_effort=48
        )
        self.assertAlmostEqual(session_load(easy), 24.0)
        self.assertGreater(session_load(hard), session_load(easy))

    def test_higher_heart_rate_is_a_heavier_impulse(self):
        easy = _run(date(2026, 1, 1), 60, 10, hr=130)
        hard = _run(date(2026, 1, 1), 60, 10, hr=170)
        self.assertGreater(session_load(hard, 190), session_load(easy, 190))

    def test_a_ride_does_not_enter_the_running_impulse(self):
        ride = Session(CROSS_EASY, "spin", "Ride", date(2026, 1, 1), duration_min=90, avg_hr=140, max_hr=190)
        self.assertGreater(session_load(ride), 0)
        self.assertEqual(running_impulse(ride), 0)

    def test_running_ctl_ignores_the_ride(self):
        start = date(2026, 1, 1)
        sessions = [_run(start + timedelta(days=i), 40, 7, hr=140) for i in range(0, 40, 2)]
        sessions.append(
            Session(CROSS_EASY, "long ride", "Ride", start + timedelta(days=10), duration_min=180, avg_hr=130, max_hr=190)
        )
        load = build_load_snapshot(sessions, start + timedelta(days=40))
        self.assertGreater(load.ctl, load.running_ctl)

    def test_long_history_does_not_open_at_zero(self):
        start = date(2026, 1, 1)
        sessions = [_run(start + timedelta(days=i), 60, 10) for i in range(40)]
        short = sessions[:10]
        annotate_session_banister(short)
        self.assertEqual(short[0].ctl_before, 0)
        annotate_session_banister(sessions)
        self.assertGreater(sessions[0].ctl_before, 0)


class SeriesTests(unittest.TestCase):
    def test_drift_and_dropped_easy_points(self):
        day = date(2026, 3, 1)
        splits = []
        for km in range(8):
            hr = 130 if km < 4 else 140
            moving = 420 if km == 0 else 360
            splits.append({"distance_m": 1000, "moving_time_s": moving, "average_heartrate": hr})
        session = _run(day, 48, 8, hr=140)
        session.splits = splits
        wiped = _run(day + timedelta(days=1), 50, 8, hr=140)
        points = performance_points(
            [session, wiped],
            [{"day": wiped.when, "actual_type": "easy_run", "feeling": "wiped", "effort_fit": "too_hard"}],
        )
        self.assertEqual(len(points), 2)
        self.assertTrue(points[0].kept)
        self.assertGreater(points[0].drift, 0.05)
        self.assertFalse(points[1].kept)
        # First kilometre is out of the steady pace, and the rest are 6:00.
        self.assertAlmostEqual(points[0].pace_min_km, 6.0, places=2)

    def test_three_too_hard_answers_slow_the_easy_center(self):
        today = date(2026, 4, 1)
        sessions = [_run(today - timedelta(days=i), 48, 8) for i in range(1, 6)]
        bare = build_paces(sessions, Prefs.defaults(), today)
        feedback = [
            {
                "day": today - timedelta(days=i),
                "recovery_band": "good",
                "compliance": "match",
                "actual_type": "easy_run",
                "effort_fit": "too_hard",
            }
            for i in range(1, 4)
        ]
        nudged = build_paces(sessions, Prefs.defaults(), today, feedback)
        self.assertAlmostEqual(pace_nudge_min(feedback, EASY_RUN), 5 / 60)
        self.assertGreater(nudged.easy_min, bare.easy_min)

    def test_one_tap_does_not_move_the_center(self):
        today = date(2026, 4, 1)
        feedback = [
            {
                "day": today - timedelta(days=1),
                "recovery_band": "good",
                "compliance": "match",
                "actual_type": "easy_run",
                "effort_fit": "too_hard",
            }
        ]
        self.assertEqual(pace_nudge_min(feedback, EASY_RUN), 0)


class FitTests(unittest.TestCase):
    def test_gain_stays_near_one_without_history(self):
        today = date(2026, 5, 1)
        sessions = [_run(today - timedelta(days=1), 40, 7, hr=140)]
        self.assertEqual(fit_fatigue_gain(sessions, [], today, 190), 1.0)

    def test_slow_easy_days_after_load_raise_the_gain(self):
        start = date(2026, 1, 1)
        sessions = []
        feedback = []
        for i in range(50):
            day = start + timedelta(days=i)
            if i < 30:
                sessions.append(_run(day, 30, 5, hr=140))
                if i % 3 == 0:
                    feedback.append(
                        {
                            "day": day,
                            "recovery_band": "good",
                            "compliance": "match",
                            "actual_type": "easy_run",
                            "effort_fit": "about_right",
                            "feeling": "ok",
                        }
                    )
            else:
                sessions.append(_run(day, 90, 12, hr=150, kind=LONG_RUN))
                sessions.append(_run(day, 40, 5.5, hr=155))
                feedback.append(
                    {
                        "day": day,
                        "recovery_band": "good",
                        "compliance": "match",
                        "actual_type": "easy_run",
                        "effort_fit": "too_hard",
                        "feeling": "wiped",
                    }
                )
        gain = fit_fatigue_gain(sessions, feedback, start + timedelta(days=49), 190)
        self.assertGreater(gain, 1.0)
        self.assertLess(gain, 1.8)

    def test_projected_form_uses_the_gain(self):
        today = date(2026, 6, 1)
        sessions = [_run(today - timedelta(days=i), 40, 7) for i in range(1, 8)]
        load = build_load_snapshot(sessions, today)
        paces = build_paces(sessions, Prefs.defaults(), today)
        from coach.periodize import PlanDay

        rest = [
            PlanDay(today + timedelta(days=i), "rest", 0, 0, None, None, "Rest", "base", "calendar")
            for i in range(7)
        ]
        fresh = _projected_form(rest, load, paces)
        heavy = load.__class__(**{**load.__dict__, "fatigue_gain": 1.8})
        tired = _projected_form(rest, heavy, paces)
        self.assertLess(tired, fresh)


class BacktestTests(unittest.TestCase):
    def test_steady_easy_pace_is_inside_the_band(self):
        start = date(2026, 1, 1)
        today = start + timedelta(days=70)
        sessions = [_run(start + timedelta(days=i), 48, 8, hr=140) for i in range(0, 70, 2)]
        feedback = [
            {
                "day": start + timedelta(days=i),
                "recovery_band": "good",
                "effort_fit": "about_right",
                "feeling": "ok",
            }
            for i in range(0, 8, 2)
        ]
        feedback.append(
            {
                "day": start + timedelta(days=10),
                "recovery_band": "good",
                "effort_fit": "too_hard",
                "feeling": "wiped",
            }
        )
        report = backtest_report(sessions, feedback, Prefs.defaults(), today, 190)
        self.assertGreater(report["cutoffs"], 0)
        self.assertGreater(report["points"], 0)
        self.assertEqual(report["coverage"], 1)
        self.assertEqual(report["baseline_coverage"], 1)
        self.assertLess(report["riegel_mae"], 0.05)
        self.assertAlmostEqual(report["good_morning_hard_rate"], 0.2)
        self.assertLessEqual(report["rel_var"], 0.11)


class ReadinessTests(unittest.TestCase):
    def test_unrelated_strain_does_not_scale_fatigue(self):
        start = date(2026, 1, 1)
        today = start + timedelta(days=40)
        sessions = [_run(start + timedelta(days=i), 48, 8, hr=140) for i in range(40)]
        rows = [
            {"day": start + timedelta(days=i), "hrv_ratio": 1.0, "resting_hr": 48, "temp_dev": 0.0}
            for i in range(40)
        ]
        self.assertEqual(readiness_factor(sessions, rows, today, 190), 1.0)

    def test_strain_that_tracks_slower_pace_scales_fatigue(self):
        start = date(2026, 1, 1)
        today = start + timedelta(days=80)
        sessions = []
        rows = []
        for i in range(80):
            day = start + timedelta(days=i)
            strained = i % 2 == 0 and i < 55
            minutes = 56 if strained else 44
            sessions.append(_run(day, minutes, 8, hr=140))
            rows.append(
                {
                    "day": day,
                    "hrv_ratio": 0.7 if strained or i >= 74 else 1.15,
                    "resting_hr": 54 if strained or i >= 74 else 46,
                    "temp_dev": 0.4 if strained or i >= 74 else -0.1,
                }
            )
        factor = readiness_factor(sessions, rows, today, 190)
        self.assertGreater(factor, 1.0)
        self.assertLessEqual(factor, 1.15)


if __name__ == "__main__":
    unittest.main()
