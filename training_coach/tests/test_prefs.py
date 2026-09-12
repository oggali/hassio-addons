"""Prefs, race-time parsing, and DuckDB prefs history."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from entities import FEEDBACK_HELPER_IDS, PREF_HELPER_IDS  # noqa: E402
from goal import (  # noqa: E402
    Prefs,
    format_hms,
    normalize_race_distance,
    parse_target_seconds,
    phase_for,
)
from prefs import HELPER_CREATE_SPECS, PrefsManager, prefs_from_states  # noqa: E402
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


class FakeClient:
    def __init__(self, existing: dict | None = None) -> None:
        self.states = dict(existing or {})
        self.base_url = "http://supervisor/core/api"
        self.token = "token"
        self.services: list[tuple[str, str, dict | None]] = []

    def get_state(self, entity_id: str):
        return self.states.get(entity_id)

    def call_service(self, domain: str, service: str, data=None):
        self.services.append((domain, service, data))
        return None


class FakeWs:
    instances: list["FakeWs"] = []

    def __init__(self, api_url: str, token: str, timeout: int = 20) -> None:
        self.api_url = api_url
        self.token = token
        self.timeout = timeout
        self.commands: list[tuple[str, dict | None]] = []
        self.closed = False
        FakeWs.instances.append(self)

    def connect(self) -> None:
        return None

    def command(self, command_type: str, data=None):
        self.commands.append((command_type, data))
        name = (data or {}).get("name", "x")
        return {"id": str(name).lower().replace(" ", "_")}

    def close(self) -> None:
        self.closed = True


class BoomWs:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def connect(self) -> None:
        raise RuntimeError("no websocket")

    def close(self) -> None:
        return None


class EnsureHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeWs.instances = []

    def test_specs_cover_all_helper_ids(self):
        ids = {entity_id for _, entity_id, _ in HELPER_CREATE_SPECS}
        self.assertEqual(ids, set(PREF_HELPER_IDS + FEEDBACK_HELPER_IDS))

    def test_creates_missing_helpers_over_websocket(self):
        client = FakeClient()
        with patch("prefs.HaWebsocket", FakeWs):
            PrefsManager(client, None).ensure_helpers()  # type: ignore[arg-type]
        self.assertEqual(len(FakeWs.instances), 1)
        session = FakeWs.instances[0]
        self.assertTrue(session.closed)
        self.assertEqual(len(session.commands), len(HELPER_CREATE_SPECS))
        self.assertEqual(session.commands[0][0], "input_datetime/create")
        self.assertEqual(session.commands[1][0], "input_select/create")
        self.assertEqual(client.services, [])

    def test_skips_helpers_that_already_exist(self):
        existing = {entity_id: {"state": "on"} for _, entity_id, _ in HELPER_CREATE_SPECS}
        client = FakeClient(existing)
        with patch("prefs.HaWebsocket", FakeWs):
            PrefsManager(client, None).ensure_helpers()  # type: ignore[arg-type]
        self.assertEqual(FakeWs.instances, [])
        self.assertEqual(client.services, [])

    def test_rest_fallback_when_websocket_unavailable(self):
        client = FakeClient()
        with patch("prefs.HaWebsocket", BoomWs):
            PrefsManager(client, None).ensure_helpers()  # type: ignore[arg-type]
        self.assertEqual(len(client.services), len(HELPER_CREATE_SPECS))
        self.assertEqual(client.services[0][:2], ("input_datetime", "create"))


if __name__ == "__main__":
    unittest.main()
