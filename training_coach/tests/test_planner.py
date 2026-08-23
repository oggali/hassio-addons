"""Planner tests using fixture Home Assistant states."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from classify import EASY_RUN, INTERVALS, LONG_RUN, REST, STRENGTH, TEMPO, classify_run  # noqa: E402
from entities import (  # noqa: E402
    GARMIN_BODY_BATTERY,
    GARMIN_HRV_BASELINE,
    GARMIN_HRV_NIGHT,
    GARMIN_TRAINING_READINESS,
    OURA_HRV_BALANCE,
    OURA_READINESS,
    OURA_REST_MODE,
    OURA_SLEEP,
    OURA_SLEEP_HRV,
    OURA_TEMP,
    strava_slot_ids,
)
from features import build_snapshot  # noqa: E402
from planner import plan_day  # noqa: E402
from settings import Settings  # noqa: E402

TZ = ZoneInfo("Europe/Helsinki")
SATURDAY = datetime(2026, 8, 22, 7, 30, tzinfo=TZ)
WEDNESDAY = datetime(2026, 8, 19, 7, 30, tzinfo=TZ)


def entity(state, updated=None, **attrs):
    stamp = (updated or SATURDAY).isoformat()
    return {
        "state": "" if state is None else str(state),
        "attributes": attrs,
        "last_updated": stamp,
        "last_changed": stamp,
    }


def good_recovery() -> dict:
    return {
        OURA_READINESS: entity(82, SATURDAY),
        OURA_SLEEP: entity(80, SATURDAY),
        OURA_SLEEP_HRV: entity(45),
        OURA_HRV_BALANCE: entity(85),
        OURA_TEMP: entity(0.1),
        OURA_REST_MODE: entity("off"),
        GARMIN_TRAINING_READINESS: entity(78),
        GARMIN_BODY_BATTERY: entity(72),
        GARMIN_HRV_NIGHT: entity(42),
        GARMIN_HRV_BASELINE: entity(40),
    }


def poor_recovery() -> dict:
    states = good_recovery()
    states[OURA_READINESS] = entity(48, SATURDAY)
    states[OURA_SLEEP] = entity(52, SATURDAY)
    states[GARMIN_BODY_BATTERY] = entity(22)
    states[GARMIN_HRV_NIGHT] = entity(30)
    states[GARMIN_HRV_BASELINE] = entity(40)
    return states


def add_strava(states: dict, index: int, title: str, sport: str, when: datetime, minutes: int, avg_hr=140, max_hr=175):
    slot = strava_slot_ids("sensor.strava_oskari_vuorinen", index)
    states[slot.activity] = entity(title, sport_type=sport)
    states[slot.date] = entity(when.isoformat())
    states[slot.distance] = entity(minutes * 180)
    states[slot.moving_time] = entity(minutes * 60)
    states[slot.elapsed_time] = entity(minutes * 60)
    states[slot.average_heartrate] = entity(avg_hr)
    states[slot.max_heartrate] = entity(max_hr)
    return states


class ClassifyTests(unittest.TestCase):
    def test_title_keywords(self):
        self.assertEqual(classify_run("Morning intervals", 40, 165, 180, 75), INTERVALS)
        self.assertEqual(classify_run("Tempo threshold", 45, 160, 180, 75), TEMPO)
        self.assertEqual(classify_run("Sunday long", 50, 140, 170, 75), LONG_RUN)
        self.assertEqual(classify_run("Easy shakeout", 90, 130, 160, 75), EASY_RUN)

    def test_long_from_duration(self):
        self.assertEqual(classify_run("Afternoon run", 95, 140, 170, 75), LONG_RUN)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(timezone="Europe/Helsinki", run_immediately=False)

    def plan(self, states, now):
        snap = build_snapshot(states, self.settings, now=now)
        return plan_day(snap, self.settings)

    def test_rest_mode(self):
        states = good_recovery()
        states[OURA_REST_MODE] = entity("on")
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertIn("Rest mode", plan.why)

    def test_poor_recovery(self):
        plan = self.plan(poor_recovery(), SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertEqual(plan.recovery_band, "poor")

    def test_long_run_yesterday(self):
        states = good_recovery()
        add_strava(states, 0, "Sunday long", "Run", SATURDAY - timedelta(days=1), 95, avg_hr=138)
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, EASY_RUN)
        self.assertEqual(plan.yesterday, LONG_RUN)

    def test_quality_already_this_week_weekend_long(self):
        states = good_recovery()
        add_strava(states, 0, "Track intervals", "Run", SATURDAY - timedelta(days=3), 40, avg_hr=168, max_hr=185)
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, LONG_RUN)

    def test_two_quality_blocks_more_quality(self):
        states = good_recovery()
        # Wednesday: already two quality days this week, not weekend
        add_strava(states, 0, "Intervals", "Run", WEDNESDAY - timedelta(days=4), 40, avg_hr=170, max_hr=188)
        add_strava(states, 1, "Tempo", "Run", WEDNESDAY - timedelta(days=2), 50, avg_hr=162, max_hr=180)
        add_strava(states, 2, "Gym", "WeightTraining", WEDNESDAY - timedelta(days=1), 50)
        plan = self.plan(states, WEDNESDAY)
        self.assertNotIn(plan.session_type, {INTERVALS, TEMPO})

    def test_no_strava_weekend_is_long(self):
        plan = self.plan(good_recovery(), SATURDAY)
        self.assertEqual(plan.session_type, LONG_RUN)

    def test_no_strava_weekday_is_quality(self):
        states = good_recovery()
        for eid, ent in list(states.items()):
            if eid.startswith("sensor.oura"):
                states[eid] = entity(ent["state"], WEDNESDAY, **ent.get("attributes", {}))
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.session_type, INTERVALS)

    def test_strength_when_ok_and_due(self):
        states = good_recovery()
        states[OURA_READINESS] = entity(68, WEDNESDAY)
        states[OURA_SLEEP] = entity(66, WEDNESDAY)
        states[GARMIN_TRAINING_READINESS] = entity(62)
        states[GARMIN_BODY_BATTERY] = entity(48)
        add_strava(states, 0, "Easy run", "Run", WEDNESDAY - timedelta(days=1), 40, avg_hr=135)
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.recovery_band, "ok")
        self.assertEqual(plan.session_type, STRENGTH)

    def test_already_trained_today(self):
        states = good_recovery()
        add_strava(states, 0, "Easy run", "Run", SATURDAY, 40)
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertIn("already", plan.why.lower())


if __name__ == "__main__":
    unittest.main()
