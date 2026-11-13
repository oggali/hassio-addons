"""Public planning entry point used by the API."""

from __future__ import annotations

import unittest
from datetime import date
from zoneinfo import ZoneInfo

from coach.classify import EASY_RUN, LONG_RUN, REST
from coach.engine import plan_from_payload
from coach.inputs import activity_from_payload, recovery_from_signals


class EngineTests(unittest.TestCase):
    def test_good_saturday_is_a_long_run(self):
        result = plan_from_payload(
            today=date(2026, 8, 22),
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
        )
        self.assertEqual(result.plan.session_type, LONG_RUN)
        self.assertIn("Today:", result.as_dict()["morning_message"])

    def test_poor_recovery_is_rest(self):
        result = plan_from_payload(
            today=date(2026, 8, 19),
            timezone="Europe/Helsinki",
            recovery={"oura_readiness": 48, "oura_sleep": 50},
        )
        self.assertEqual(result.plan.session_type, REST)
        self.assertEqual(result.plan.recovery_band, "poor")

    def test_garmin_recovery_hours_are_hours_above_48(self):
        recovery, awake, _ = recovery_from_signals(
            {"garmin_awake": True, "garmin_readiness": 70, "garmin_recovery_hours": 72},
            date(2026, 8, 19),
            ZoneInfo("Europe/Helsinki"),
        )
        self.assertTrue(awake)
        self.assertEqual(recovery.garmin_recovery_hours, 72)
        self.assertIn("Garmin still wants 72h recovery", recovery.reasons)

    def test_strava_and_garmin_copies_collapse(self):
        start = "2026-08-19T07:30:00+03:00"
        result = plan_from_payload(
            today=date(2026, 8, 22),
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
            sessions=[
                {
                    "id": "strava:1",
                    "source": "strava",
                    "activity_id": "1",
                    "title": "Easy",
                    "sport": "Run",
                    "when": "2026-08-19",
                    "started_at": start,
                    "duration_min": 40,
                    "distance_m": 7000,
                },
                {
                    "id": "garmin:9",
                    "source": "garmin",
                    "activity_id": "9",
                    "title": "Helsinki",
                    "sport": "running",
                    "when": "2026-08-19",
                    "started_at": start,
                    "duration_min": 41,
                    "distance_m": 7100,
                },
            ],
        )
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.sessions[0]["source"], "strava")
        self.assertEqual(result.sessions[0]["session_type"], EASY_RUN)

    def test_day_activity_fuses_oura_and_garmin(self):
        activity = activity_from_payload(
            {"oura_steps": 9000, "garmin_steps": 11000, "oura_active_kcal": 400}
        )
        self.assertEqual(activity.steps, 11000)
        self.assertEqual(activity.active_kcal, 400)

    def test_friday_long_does_not_keep_saturday_long(self):
        friday = date(2026, 8, 21)
        result = plan_from_payload(
            today=friday,
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
            sessions=[
                {
                    "source": "strava",
                    "activity_id": "1",
                    "title": "Track intervals",
                    "sport": "Run",
                    "when": "2026-08-18",
                    "started_at": "2026-08-18T18:00:00+03:00",
                    "duration_min": 45,
                    "distance_m": 8000,
                }
            ],
        )
        self.assertEqual(result.plan.session_type, LONG_RUN)
        self.assertIn("Friday is a reasonable backup", result.plan.why)
        saturday = next(day for day in result.calendar if day.day == date(2026, 8, 22))
        sunday = next(day for day in result.calendar if day.day == date(2026, 8, 23))
        self.assertEqual(saturday.session_type, EASY_RUN)
        self.assertEqual(sunday.session_type, REST)
        message = result.as_dict()["morning_message"]
        self.assertIn("Sat: easy run", message)
        self.assertNotIn("Sat: long run", message)

    def test_friday_intervals_do_not_keep_saturday_long(self):
        result = plan_from_payload(
            today=date(2026, 8, 21),
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
        )
        self.assertEqual(result.plan.session_type, "intervals")
        saturday = next(day for day in result.calendar if day.day == date(2026, 8, 22))
        self.assertEqual(saturday.session_type, EASY_RUN)

    def test_locked_saturday_long_stays_when_friday_cannot_stack_it(self):
        result = plan_from_payload(
            today=date(2026, 8, 21),
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
            locks={"sat": "long_run"},
            sessions=[
                {
                    "source": "strava",
                    "activity_id": "1",
                    "title": "Track intervals",
                    "sport": "Run",
                    "when": "2026-08-18",
                    "started_at": "2026-08-18T18:00:00+03:00",
                    "duration_min": 45,
                    "distance_m": 8000,
                }
            ],
        )
        self.assertNotEqual(result.plan.session_type, LONG_RUN)
        saturday = next(day for day in result.calendar if day.day == date(2026, 8, 22))
        self.assertEqual(saturday.session_type, LONG_RUN)
        self.assertEqual(saturday.source, "lock")

    def test_filled_long_quota_leaves_saturday_long(self):
        result = plan_from_payload(
            today=date(2026, 8, 21),
            timezone="Europe/Helsinki",
            recovery={"feel": "good"},
            sessions=[
                {
                    "source": "strava",
                    "activity_id": "1",
                    "title": "Sunday long",
                    "sport": "Run",
                    "when": "2026-08-16",
                    "started_at": "2026-08-16T09:00:00+03:00",
                    "duration_min": 100,
                    "distance_m": 18000,
                },
                {
                    "source": "strava",
                    "activity_id": "2",
                    "title": "Track intervals",
                    "sport": "Run",
                    "when": "2026-08-18",
                    "started_at": "2026-08-18T18:00:00+03:00",
                    "duration_min": 45,
                    "distance_m": 8000,
                },
            ],
        )
        self.assertNotIn(result.plan.session_type, {LONG_RUN, "intervals", "tempo"})
        saturday = next(day for day in result.calendar if day.day == date(2026, 8, 22))
        self.assertEqual(saturday.session_type, LONG_RUN)


if __name__ == "__main__":
    unittest.main()
