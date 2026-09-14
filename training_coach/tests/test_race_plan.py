"""Pace bands, periodization, finish-time MC, feedback matching."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from classify import EASY_RUN, INTERVALS, LONG_RUN, REST, STRENGTH, TEMPO, Session  # noqa: E402
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
)
from features import DayActivity, build_snapshot  # noqa: E402
from feedback import (  # noqa: E402
    ACK_TIMEOUT_SECONDS,
    TAG_CHECKIN_COMP,
    TAG_CHECKIN_FEEL,
    TAG_CHECKIN_SKIP,
    android_followups,
    classify_compliance,
    coaching_note,
    describe_evening_tomorrow,
    describe_next_session,
    format_logged_label,
    logged_sessions,
    parse_coach_action,
    primary_actual,
    recap_text,
    resolve_tomorrow_row,
)
from goal import Prefs  # noqa: E402
from load import build_load_snapshot  # noqa: E402
from main import handle_mobile_action  # noqa: E402
from paces import build_paces, easy_pace_min_km, format_pace, riegel  # noqa: E402
from periodize import build_skeleton  # noqa: E402
from planner import plan_day  # noqa: E402
from settings import Settings  # noqa: E402
from simulate import finish_distribution, search_calendar  # noqa: E402

TZ = ZoneInfo("Europe/Helsinki")
SATURDAY = date(2026, 8, 22)


def _session(kind, day, km, minutes, title="run"):
    return Session(
        session_type=kind,
        title=title,
        sport="Run",
        when=day,
        duration_min=minutes,
        distance_m=km * 1000,
        source="test",
    )


class PaceTests(unittest.TestCase):
    def test_riegel_and_format(self):
        t = riegel(20 * 60, 5, 10, 1.06)
        self.assertGreater(t, 20 * 60)
        self.assertEqual(format_pace(5 + 50 / 60), "5:50")

    def test_easy_pace_from_history(self):
        sessions = [
            _session(EASY_RUN, SATURDAY - timedelta(days=i), 8, 48) for i in range(6)
        ]
        pace = easy_pace_min_km(sessions, SATURDAY)
        self.assertAlmostEqual(pace, 6.0, places=1)

    def test_target_sets_race_pace(self):
        sessions = [_session(EASY_RUN, SATURDAY - timedelta(days=1), 8, 48)]
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="half", target_time="1:45:00")
        paces = build_paces(sessions, prefs, SATURDAY)
        self.assertIsNotNone(paces.race_pace)
        self.assertIsNotNone(paces.predicted_s)
        self.assertGreater(paces.predicted_s, 6300)
        self.assertGreater(paces.easy_min, paces.interval_min)


class PeriodizeTests(unittest.TestCase):
    def test_aligns_to_race_day(self):
        today = date(2026, 9, 12)
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="half", target_time="1:45:00")
        sessions = [_session(EASY_RUN, today - timedelta(days=1), 8, 48)]
        load = build_load_snapshot(sessions, today)
        paces = build_paces(sessions, prefs, today)
        days = build_skeleton(today, prefs, load, paces, sessions)
        self.assertEqual(days[-1].day, prefs.race_date)
        self.assertEqual(days[-1].session_type, LONG_RUN)
        self.assertEqual(days[-1].structure, "Race day")
        self.assertTrue(any(d.session_type in {INTERVALS, TEMPO} for d in days))

    def test_insane_target_does_not_explode_volume(self):
        today = date(2026, 9, 12)
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="marathon", target_time="2:10:00")
        sessions = [_session(EASY_RUN, today - timedelta(days=1), 6, 40)]
        load = build_load_snapshot(sessions, today)
        paces = build_paces(sessions, prefs, today)
        finish = finish_distribution(paces, prefs, seed=1)
        self.assertFalse(finish["feasible"])
        skeleton = build_skeleton(today, prefs, load, paces, sessions)
        adjusted = search_calendar(skeleton, load, prefs, paces, [], finish, seed=3)
        training_longs = [
            d.km_max for d in adjusted if d.session_type == LONG_RUN and d.phase != "race"
        ]
        self.assertTrue(training_longs)
        self.assertLess(max(training_longs), 20)
        self.assertLess(max(d.km_max for d in adjusted if d.session_type == LONG_RUN), 45)

    def test_no_goal_is_maintenance(self):
        today = date(2026, 9, 12)
        prefs = Prefs.defaults()
        sessions = [_session(EASY_RUN, today - timedelta(days=1), 8, 48)]
        load = build_load_snapshot(sessions, today)
        paces = build_paces(sessions, prefs, today)
        days = build_skeleton(today, prefs, load, paces, sessions)
        self.assertFalse(prefs.has_race)
        self.assertNotEqual(days[-1].structure, "Race day")
        self.assertEqual(days[-1].day, today + timedelta(days=13))

    def test_long_is_meaningfully_longer_than_easy(self):
        """7 km easy + a 13.5 km tagged long used to prescribe 12.4–14.5 km longs."""
        today = date(2026, 9, 13)
        prefs = Prefs.defaults()
        sessions = [
            _session(EASY_RUN, today - timedelta(days=i), 7.0, 42) for i in range(1, 10)
        ]
        sessions.append(_session(LONG_RUN, today - timedelta(days=6), 13.5, 81))
        load = build_load_snapshot(sessions, today)
        paces = build_paces(sessions, prefs, today)
        days = build_skeleton(today, prefs, load, paces, sessions)
        easy = next(d for d in days if d.session_type == EASY_RUN)
        long = next(d for d in days if d.session_type == LONG_RUN)
        easy_mid = (easy.km_min + easy.km_max) / 2.0
        long_mid = (long.km_min + long.km_max) / 2.0
        self.assertAlmostEqual(easy_mid, 7.0, delta=0.6)
        self.assertGreaterEqual(long_mid / easy_mid, 2.0)
        self.assertGreater(long.km_min, easy.km_max + 4.0)
        self.assertGreaterEqual(long_mid, 15.0)

    def test_weekly_longest_counts_even_if_not_tagged_long(self):
        today = date(2026, 9, 13)
        sessions = [
            _session(EASY_RUN, today - timedelta(days=i), 7.0, 42) for i in range(2, 8)
        ]
        sessions.append(
            _session(EASY_RUN, today - timedelta(days=1), 16.0, 70, title="Sunday run")
        )
        load = build_load_snapshot(sessions, today)
        self.assertGreaterEqual(load.long_km, 15.5)

    def test_quality_structure_varies_by_distance(self):
        from periodize import interval_structure

        five = interval_structure(Prefs(race_distance="5k"), [], None, "build")
        half = interval_structure(Prefs(race_distance="half"), [], None, "build")
        mara = interval_structure(Prefs(race_distance="marathon"), [], None, "build")
        self.assertIn("400", five[0])
        self.assertIn("1000", half[0])
        self.assertNotEqual(five[0], mara[0])

    def test_interval_ladder_holds_after_skip(self):
        from periodize import interval_structure

        prefs = Prefs(race_distance="5k")
        last = _session(INTERVALS, SATURDAY - timedelta(days=3), 8, 50, title="intervals")
        stepped = interval_structure(prefs, [last], "ok", "build", last_compliance="match")
        held = interval_structure(prefs, [last], "tired", "build", last_compliance="skipped")
        self.assertNotEqual(stepped[0], held[0])


class FinishMcTests(unittest.TestCase):
    def test_deterministic_seed(self):
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="half", target_time="1:45:00")
        paces = build_paces([], prefs, SATURDAY)
        a = finish_distribution(paces, prefs, seed=42)
        b = finish_distribution(paces, prefs, seed=42)
        self.assertEqual(a["p10"], b["p10"])
        self.assertEqual(a["p90"], b["p90"])
        self.assertLess(a["p10"], a["p50"])
        self.assertLess(a["p50"], a["p90"])


class FeedbackTests(unittest.TestCase):
    def test_compliance(self):
        self.assertEqual(classify_compliance(REST, None), "match")
        self.assertEqual(classify_compliance(INTERVALS, None), "skipped")
        self.assertEqual(classify_compliance(INTERVALS, TEMPO), "same_family")
        self.assertEqual(classify_compliance(INTERVALS, EASY_RUN), "substituted")
        self.assertEqual(classify_compliance(REST, EASY_RUN), "extra")
        self.assertEqual(
            classify_compliance(STRENGTH, INTERVALS, actuals=[INTERVALS, STRENGTH]),
            "match",
        )
        self.assertEqual(
            classify_compliance(REST, INTERVALS, actuals=[INTERVALS, STRENGTH]),
            "extra",
        )

    def test_two_sessions_listed_in_recap(self):
        day = date(2026, 9, 14)
        sessions = [
            Session(
                INTERVALS,
                "Track",
                "Run",
                day,
                duration_min=42,
                distance_m=7200,
                activity_id="1",
            ),
            Session(
                STRENGTH,
                "Gym",
                "WeightTraining",
                day,
                duration_min=50,
                activity_id="2",
            ),
        ]
        logged = logged_sessions(sessions, day)
        self.assertEqual([s.session_type for s in logged], [INTERVALS, STRENGTH])
        self.assertEqual(primary_actual(sessions, day), INTERVALS)
        label = format_logged_label(logged)
        self.assertIn("intervals", label)
        self.assertIn("7.2 km", label)
        self.assertIn("gym / strength", label)
        self.assertIn("50 min", label)
        text = recap_text(
            "Rest day",
            REST,
            INTERVALS,
            "extra",
            ask_helpers=False,
            tomorrow="intervals 6.6–8.4 km @ 4:58–5:18",
            logged_label=label,
            extras=[STRENGTH],
            logged_count=2,
        )
        self.assertIn("Logged: intervals 7.2 km, gym / strength 50 min", text)
        self.assertIn("Extra sessions on a rest day", text)
        self.assertNotRegex(text, r"Logged: intervals \(planned")

    def test_planned_session_still_matches_when_stacked(self):
        note = coaching_note(
            "match",
            STRENGTH,
            STRENGTH,
            extras=[INTERVALS],
            logged_count=2,
        )
        self.assertIn("Plus extra intervals", note)

    def test_evening_tomorrow_flags_stacked_quality(self):
        today = [
            Session(INTERVALS, "Track", "Run", date(2026, 9, 14), duration_min=42, distance_m=7200),
        ]
        row = {
            "session_type": INTERVALS,
            "km": "6.6–8.4 km",
            "pace": "4:58–5:18",
        }
        text = describe_evening_tomorrow(row, today)
        self.assertIn("not intervals", text)
        self.assertIn("too soon after today’s intervals", text)
        self.assertIn("Calendar had intervals 6.6–8.4 km @ 4:58–5:18", text)
        self.assertIn("morning will switch it", text)

    def test_evening_tomorrow_keeps_calendar_when_spacing_ok(self):
        gym = [Session(STRENGTH, "Gym", "WeightTraining", date(2026, 9, 14), duration_min=50)]
        row = {"session_type": INTERVALS, "km": "6.6–8.4 km", "pace": "4:58–5:18"}
        self.assertEqual(
            describe_evening_tomorrow(row, gym),
            "intervals 6.6–8.4 km @ 4:58–5:18",
        )
        easy_cal = {"session_type": "easy_run", "km": "6–10 km"}
        quality = [
            Session(INTERVALS, "Track", "Run", date(2026, 9, 14), duration_min=42),
        ]
        self.assertEqual(describe_evening_tomorrow(easy_cal, quality), "easy run 6–10 km")

    def test_parse_android_action(self):
        parsed = parse_coach_action("coach_2026-09-12_feel_great")
        self.assertEqual(parsed["option"], "great")
        self.assertEqual(parsed["field"], "feeling")
        skipped = parse_coach_action("coach_2026-09-12_comp_skipped")
        self.assertEqual(skipped["option"], "skipped")
        other = parse_coach_action("coach_2026-09-12_skip_other", "weather was bad")
        self.assertEqual(other["option"], "other_sport")
        self.assertEqual(other["notes"], "weather was bad")

    def test_feeling_tap_replaces_card_with_timed_ack(self):
        parsed = parse_coach_action("coach_2026-09-12_feel_ok")
        day = date(2026, 9, 12)
        followups = android_followups(parsed, day)
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0]["message"], "Logged: OK")
        data = followups[0]["android_data"]
        self.assertEqual(data["tag"], TAG_CHECKIN_FEEL)
        self.assertEqual(data["timeout"], ACK_TIMEOUT_SECONDS)
        self.assertFalse(data["sticky"])
        self.assertNotIn("actions", data)

    def test_skipped_clears_comp_and_asks_reason(self):
        parsed = parse_coach_action("coach_2026-09-12_comp_skipped")
        day = date(2026, 9, 12)
        followups = android_followups(parsed, day)
        self.assertEqual(followups[0]["message"], "clear_notification")
        self.assertEqual(followups[0]["android_data"], {"tag": TAG_CHECKIN_COMP})
        self.assertEqual(followups[1]["message"], "Why did you skip?")
        skip_data = followups[1]["android_data"]
        self.assertEqual(skip_data["tag"], TAG_CHECKIN_SKIP)
        self.assertTrue(skip_data["sticky"])
        self.assertEqual(len(skip_data["actions"]), 3)

    def test_skip_reply_ack_uses_notes(self):
        parsed = parse_coach_action("coach_2026-09-12_skip_other", "weather was bad")
        followups = android_followups(parsed, date(2026, 9, 12))
        self.assertEqual(followups[0]["message"], "Logged: weather was bad")
        self.assertEqual(followups[0]["android_data"]["tag"], TAG_CHECKIN_SKIP)

    def test_feeling_ack_goes_to_android_not_telegram(self):
        store = MagicMock()
        store.get_feedback.return_value = {"feeling": "ok", "day": date(2026, 9, 12)}
        client = MagicMock()
        settings = Settings(
            notify_service="notify.tg_oskari",
            mobile_notify_service="notify.mobile_app_galaxys26",
        )
        handle_mobile_action(
            {"action": "coach_2026-09-12_feel_ok"},
            store,
            MagicMock(),
            client,
            settings,
        )
        notify_calls = [c for c in client.call_service.call_args_list if c.args[0] == "notify"]
        self.assertEqual(len(notify_calls), 1)
        _domain, service, payload = notify_calls[0].args
        self.assertEqual(service, "mobile_app_galaxys26")
        self.assertEqual(payload["message"], "Logged: OK")
        self.assertEqual(payload["data"]["tag"], TAG_CHECKIN_FEEL)
        self.assertFalse(payload["data"]["sticky"])
        self.assertEqual(payload["data"]["timeout"], ACK_TIMEOUT_SECONDS)

    def test_telegram_helper_prompt_when_no_android(self):
        text = recap_text("Easy run", EASY_RUN, None, "skipped", ask_helpers=True)
        self.assertIn("input_select.training_coach_feeling", text)
        silent = recap_text("Easy run", EASY_RUN, None, "skipped", ask_helpers=False)
        self.assertNotIn("input_select.training_coach_feeling", silent)

    def test_match_names_calendar_tomorrow(self):
        text = recap_text(
            "Rest day",
            REST,
            None,
            "match",
            ask_helpers=False,
            tomorrow="gym / strength",
        )
        self.assertIn("Tomorrow: gym / strength", text)
        self.assertNotIn("Easy tomorrow", text)

    def test_recap_includes_fused_activity(self):
        activity = DayActivity(
            steps=11000,
            oura_steps=9000,
            garmin_steps=11000,
            active_kcal=430,
        )
        text = recap_text(
            "Rest day",
            REST,
            None,
            "match",
            ask_helpers=False,
            activity=activity,
        )
        self.assertIn("Day activity: 11.0k steps, 430 kcal (Garmin + Oura).", text)

    def test_match_without_calendar_does_not_invent_easy(self):
        note = coaching_note("match", REST, None)
        self.assertEqual(note, "Nice — that matches the morning plan.")
        self.assertNotIn("Easy tomorrow", note)

    def test_describe_strength_and_tempo(self):
        self.assertEqual(describe_next_session({"session_type": STRENGTH}), "gym / strength")
        self.assertEqual(
            describe_next_session(
                {
                    "session": TEMPO,
                    "km": "9.9–12.6 km",
                    "pace": "5:16–5:36",
                }
            ),
            "tempo run 9.9–12.6 km @ 5:16–5:36",
        )

    def test_resolve_tomorrow_prefers_plan_row(self):
        today = date(2026, 9, 13)
        upcoming = [{"day": "2026-09-14", "session": EASY_RUN}]
        row = resolve_tomorrow_row(
            today,
            plan_row={"session_type": STRENGTH},
            upcoming=upcoming,
        )
        self.assertEqual(row["session_type"], STRENGTH)
        from_upcoming = resolve_tomorrow_row(today, upcoming=upcoming)
        self.assertEqual(from_upcoming["session"], EASY_RUN)
        self.assertIsNone(resolve_tomorrow_row(today, upcoming=[{"day": "2026-09-15", "session": TEMPO}]))


class OverlayTests(unittest.TestCase):
    def test_poor_recovery_overrides_calendar_quality(self):
        settings = Settings(timezone="Europe/Helsinki")
        stamp = "2026-08-22T07:30:00+03:00"

        def entity(state):
            return {"state": str(state), "attributes": {}, "last_updated": stamp, "last_changed": stamp}

        states = {
            OURA_READINESS: entity(48),
            OURA_SLEEP: entity(52),
            OURA_SLEEP_HRV: entity(30),
            OURA_HRV_BALANCE: entity(50),
            OURA_TEMP: entity(0.5),
            OURA_REST_MODE: entity("off"),
            GARMIN_TRAINING_READINESS: entity(40),
            GARMIN_BODY_BATTERY: entity(22),
            GARMIN_HRV_NIGHT: entity(30),
            GARMIN_HRV_BASELINE: entity(40),
        }
        from datetime import datetime as dt

        from periodize import PlanDay

        snap = build_snapshot(states, settings, now=dt(2026, 8, 22, 7, 30, tzinfo=TZ))
        intended = PlanDay(
            day=SATURDAY,
            session_type=INTERVALS,
            km_min=8,
            km_max=11,
            pace_min=4.3,
            pace_max=4.6,
            structure="8×400 m",
            phase="build",
        )
        prefs = Prefs(race_date=date(2026, 10, 4), race_distance="half", target_time="1:45:00")
        plan = plan_day(snap, settings, prefs=prefs, calendar_today=intended)
        self.assertEqual(plan.session_type, REST)
        self.assertEqual(plan.recovery_band, "poor")

    def test_recipe_km_pace_formatting(self):
        from recipes import build_recipe

        recipe = build_recipe(
            EASY_RUN,
            [],
            None,
            km_min=6,
            km_max=10,
            pace_min=5 + 50 / 60,
            pace_max=6.5,
            structure="Easy conversational / zone 2",
        )
        self.assertIn("6–10 km", recipe.title)
        self.assertIn("5:50", recipe.title)
        self.assertIn("6:30", recipe.title)

    def test_no_race_recipe_uses_history_ranges(self):
        from recipes import build_recipe

        sessions = [_session(EASY_RUN, SATURDAY - timedelta(days=1), 8, 48)]
        paces = build_paces(sessions, Prefs.defaults(), SATURDAY)
        recipe = build_recipe(EASY_RUN, sessions, None, paces=paces)
        self.assertIn("km", recipe.title)
        self.assertIn("/km", recipe.title)


if __name__ == "__main__":
    unittest.main()
