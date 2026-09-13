"""Planner tests using fixture Home Assistant states."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from classify import (  # noqa: E402
    CROSS_EASY,
    CROSS_HARD,
    CROSS_LONG,
    EASY_RUN,
    INTERVALS,
    LONG_RUN,
    OTHER,
    REST,
    STRENGTH,
    TEMPO,
    Session,
    classify_run,
    classify_sport,
    is_training_session,
)
from entities import (  # noqa: E402
    GARMIN_BODY_BATTERY,
    GARMIN_HRV_BASELINE,
    GARMIN_HRV_NIGHT,
    GARMIN_TRAINING_READINESS,
    OURA_HRV_BALANCE,
    OURA_LAST_WORKOUT_TYPE,
    OURA_READINESS,
    OURA_REST_MODE,
    OURA_SLEEP,
    OURA_SLEEP_HRV,
    OURA_TEMP,
    OURA_WORKOUTS_TODAY,
    strava_slot_ids,
)
from features import build_snapshot  # noqa: E402
from load import session_load  # noqa: E402
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

    def test_bike_effort_from_title_and_hr(self):
        self.assertEqual(classify_sport("Ride", "Easy commute", 35, 118, 140, 75), CROSS_EASY)
        self.assertEqual(classify_sport("Ride", "Zwift intervals", 50, 155, 178, 75), CROSS_HARD)
        self.assertEqual(classify_sport("VirtualRide", "Morning Ride", 45, 160, 180, 75), CROSS_HARD)
        self.assertEqual(classify_sport("Ride", "Sunday ride", 130, 128, 155, 75), CROSS_LONG)

    def test_hard_bike_load_exceeds_easy(self):
        easy = Session(CROSS_EASY, "commute", "Ride", SATURDAY.date(), duration_min=60)
        hard = Session(CROSS_HARD, "intervals", "Ride", SATURDAY.date(), duration_min=60)
        self.assertGreater(session_load(hard), session_load(easy))

    def test_nordic_ski_effort_from_title_and_hr(self):
        self.assertEqual(
            classify_sport("NordicSki", "Easy classic", 50, 125, 155, 75), CROSS_EASY
        )
        self.assertEqual(
            classify_sport("NordicSki", "Skate intervals", 45, 162, 180, 75), CROSS_HARD
        )
        self.assertEqual(
            classify_sport("RollerSki", "Skate VO2", 40, 160, 178, 75), CROSS_HARD
        )
        self.assertEqual(
            classify_sport("NordicSki", "Sunday skate", 90, 132, 160, 75), CROSS_LONG
        )
        self.assertEqual(classify_sport("AlpineSki", "Downhill day", 180, 110, 140, 75), OTHER)

    def test_walk_is_not_training(self):
        walk = Session(OTHER, "Afternoon walk", "Walk", SATURDAY.date(), duration_min=40)
        run = Session(EASY_RUN, "Easy run", "Run", SATURDAY.date(), duration_min=40)
        self.assertFalse(is_training_session(walk))
        self.assertTrue(is_training_session(run))
        self.assertEqual(classify_sport("Walk", "Afternoon walk", 40, 95, 110, 75), OTHER)
        self.assertEqual(classify_sport("walking", "walking", 40, None, None, 75), OTHER)
        self.assertEqual(classify_sport("running", "running", 50, None, None, 75), EASY_RUN)

    def test_ski_load_exceeds_same_bike(self):
        bike = Session(CROSS_HARD, "intervals", "Ride", SATURDAY.date(), duration_min=60)
        ski = Session(CROSS_HARD, "skate intervals", "NordicSki", SATURDAY.date(), duration_min=60)
        self.assertGreater(session_load(ski), session_load(bike))


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
        self.assertIn("recovery looks poor", plan.why.lower())
        self.assertNotIn("already", plan.why.lower())

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

    def test_oura_walk_is_not_already_trained(self):
        states = poor_recovery()
        states[OURA_WORKOUTS_TODAY] = entity(
            1,
            SATURDAY,
            workouts=[
                {
                    "activity": "walking",
                    "day": "2026-08-22",
                    "start_datetime": "2026-08-22T08:00:00+03:00",
                    "end_datetime": "2026-08-22T08:40:00+03:00",
                }
            ],
        )
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertIn("recovery looks poor", plan.why.lower())
        self.assertNotIn("already", plan.why.lower())

    def test_strava_walk_is_not_already_trained(self):
        states = poor_recovery()
        add_strava(states, 0, "Afternoon walk", "Walk", SATURDAY, 40, avg_hr=95, max_hr=110)
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertNotIn("already", plan.why.lower())

    def test_oura_run_is_already_trained(self):
        states = good_recovery()
        states[OURA_WORKOUTS_TODAY] = entity(
            1,
            SATURDAY,
            workouts=[
                {
                    "activity": "running",
                    "day": "2026-08-22",
                    "start_datetime": "2026-08-22T08:00:00+03:00",
                    "end_datetime": "2026-08-22T08:50:00+03:00",
                }
            ],
        )
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertIn("already", plan.why.lower())

    def test_stale_oura_count_is_not_already_trained(self):
        states = poor_recovery()
        states[OURA_WORKOUTS_TODAY] = entity(1, SATURDAY)
        states[OURA_LAST_WORKOUT_TYPE] = entity(
            "running",
            SATURDAY,
            workout={
                "activity": "running",
                "day": "2026-08-21",
                "start_datetime": "2026-08-21T18:00:00+03:00",
                "end_datetime": "2026-08-21T19:00:00+03:00",
            },
        )
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.session_type, REST)
        self.assertNotIn("already", plan.why.lower())

    def test_easy_bike_yesterday_does_not_block_quality(self):
        states = good_recovery()
        for eid, ent in list(states.items()):
            if eid.startswith("sensor.oura"):
                states[eid] = entity(ent["state"], WEDNESDAY, **ent.get("attributes", {}))
        add_strava(
            states,
            0,
            "Easy commute",
            "Ride",
            WEDNESDAY - timedelta(days=1),
            40,
            avg_hr=118,
            max_hr=140,
        )
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.yesterday, CROSS_EASY)
        self.assertEqual(plan.session_type, INTERVALS)

    def test_hard_bike_yesterday_blocks_quality(self):
        states = good_recovery()
        for eid, ent in list(states.items()):
            if eid.startswith("sensor.oura"):
                states[eid] = entity(ent["state"], WEDNESDAY, **ent.get("attributes", {}))
        add_strava(
            states,
            0,
            "Zwift intervals",
            "Ride",
            WEDNESDAY - timedelta(days=1),
            50,
            avg_hr=160,
            max_hr=180,
        )
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.yesterday, CROSS_HARD)
        self.assertNotIn(plan.session_type, {INTERVALS, TEMPO, LONG_RUN})

    def test_long_bike_yesterday_needs_recovery(self):
        states = good_recovery()
        states[OURA_READINESS] = entity(68, SATURDAY)
        states[OURA_SLEEP] = entity(66, SATURDAY)
        states[GARMIN_TRAINING_READINESS] = entity(62)
        states[GARMIN_BODY_BATTERY] = entity(48)
        add_strava(
            states,
            0,
            "Sunday ride",
            "Ride",
            SATURDAY - timedelta(days=1),
            130,
            avg_hr=128,
            max_hr=155,
        )
        plan = self.plan(states, SATURDAY)
        self.assertEqual(plan.yesterday, CROSS_LONG)
        self.assertEqual(plan.session_type, REST)

    def test_hard_ski_yesterday_blocks_quality(self):
        states = good_recovery()
        for eid, ent in list(states.items()):
            if eid.startswith("sensor.oura"):
                states[eid] = entity(ent["state"], WEDNESDAY, **ent.get("attributes", {}))
        add_strava(
            states,
            0,
            "Skate intervals",
            "NordicSki",
            WEDNESDAY - timedelta(days=1),
            50,
            avg_hr=162,
            max_hr=180,
        )
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.yesterday, CROSS_HARD)
        self.assertNotIn(plan.session_type, {INTERVALS, TEMPO, LONG_RUN})
        self.assertIn("ski", plan.why.lower())

    def test_easy_ski_yesterday_does_not_block_quality(self):
        states = good_recovery()
        for eid, ent in list(states.items()):
            if eid.startswith("sensor.oura"):
                states[eid] = entity(ent["state"], WEDNESDAY, **ent.get("attributes", {}))
        add_strava(
            states,
            0,
            "Easy classic",
            "NordicSki",
            WEDNESDAY - timedelta(days=1),
            45,
            avg_hr=125,
            max_hr=150,
        )
        plan = self.plan(states, WEDNESDAY)
        self.assertEqual(plan.yesterday, CROSS_EASY)
        self.assertEqual(plan.session_type, INTERVALS)


if __name__ == "__main__":
    unittest.main()
