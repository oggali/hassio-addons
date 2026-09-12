"""Live training prefs from HA helpers, with DuckDB history."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from entities import (
    DID_PLAN_HELPER,
    FEELING_HELPER,
    RACE_DATE_HELPER,
    RACE_DISTANCE_HELPER,
    SKIP_REASON_HELPER,
    TARGET_TIME_HELPER,
    WEEKLY_LONG_HELPER,
    WEEKLY_QUALITY_HELPER,
    WEEKLY_REST_HELPER,
    WEEKLY_STRENGTH_HELPER,
)
from goal import (
    DID_PLAN_OPTIONS,
    FEELING_OPTIONS,
    RACE_DISTANCES,
    SKIP_REASON_OPTIONS,
    Prefs,
    clamp_int,
    normalize_race_distance,
    parse_race_date,
)
from ha_client import HomeAssistantClient
from ha_ws import HaWebsocket
from parse import is_unavailable, parse_float, state_value
from store import CoachStore


def _log(message: str) -> None:
    print(f"[training_coach] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def prefs_from_states(states: dict[str, dict[str, Any]], today: date | None = None) -> Prefs:
    today = today or date.today()
    race_raw = state_value(states.get(RACE_DATE_HELPER))
    target_raw = state_value(states.get(TARGET_TIME_HELPER))
    distance_raw = state_value(states.get(RACE_DISTANCE_HELPER))
    return Prefs(
        race_date=parse_race_date(None if is_unavailable(race_raw) else str(race_raw), today),
        race_distance=normalize_race_distance(
            None if is_unavailable(distance_raw) else str(distance_raw)
        ),
        target_time="" if is_unavailable(target_raw) else str(target_raw).strip(),
        weekly_long_runs=clamp_int(parse_float(state_value(states.get(WEEKLY_LONG_HELPER))), 1, 0, 3),
        weekly_quality_runs=clamp_int(
            parse_float(state_value(states.get(WEEKLY_QUALITY_HELPER))), 1, 0, 4
        ),
        weekly_strength=clamp_int(
            parse_float(state_value(states.get(WEEKLY_STRENGTH_HELPER))), 2, 0, 5
        ),
        weekly_rest_days=clamp_int(parse_float(state_value(states.get(WEEKLY_REST_HELPER))), 1, 0, 4),
        source="helper",
    )


def read_feedback_helpers(states: dict[str, dict[str, Any]]) -> dict[str, str]:
    def option(entity_id: str, allowed: tuple[str, ...]) -> str:
        raw = state_value(states.get(entity_id))
        if is_unavailable(raw):
            return "unset"
        text = str(raw).strip().lower()
        return text if text in allowed else "unset"

    return {
        "feeling": option(FEELING_HELPER, FEELING_OPTIONS),
        "did_plan": option(DID_PLAN_HELPER, DID_PLAN_OPTIONS),
        "skip_reason": option(SKIP_REASON_HELPER, SKIP_REASON_OPTIONS),
    }


# Home Assistant no longer exposes input_*/create REST services. Helpers are
# created with the same websocket collection API as Settings → Helpers.
HELPER_CREATE_SPECS: list[tuple[str, str, dict[str, Any]]] = [
    (
        "input_datetime",
        RACE_DATE_HELPER,
        {
            "name": "Training coach race date",
            "has_date": True,
            "has_time": False,
            "icon": "mdi:calendar",
        },
    ),
    (
        "input_select",
        RACE_DISTANCE_HELPER,
        {
            "name": "Training coach race distance",
            "options": list(RACE_DISTANCES),
            "initial": "none",
            "icon": "mdi:map-marker-distance",
        },
    ),
    (
        "input_text",
        TARGET_TIME_HELPER,
        {
            "name": "Training coach target time",
            "initial": "",
            "min": 0,
            "max": 16,
            "icon": "mdi:timer-outline",
        },
    ),
    (
        "input_number",
        WEEKLY_LONG_HELPER,
        {
            "name": "Training coach weekly long runs",
            "min": 0,
            "max": 3,
            "step": 1,
            "initial": 1,
            "mode": "box",
            "icon": "mdi:run",
        },
    ),
    (
        "input_number",
        WEEKLY_QUALITY_HELPER,
        {
            "name": "Training coach weekly quality runs",
            "min": 0,
            "max": 4,
            "step": 1,
            "initial": 1,
            "mode": "box",
            "icon": "mdi:lightning-bolt",
        },
    ),
    (
        "input_number",
        WEEKLY_STRENGTH_HELPER,
        {
            "name": "Training coach weekly strength",
            "min": 0,
            "max": 5,
            "step": 1,
            "initial": 2,
            "mode": "box",
            "icon": "mdi:dumbbell",
        },
    ),
    (
        "input_number",
        WEEKLY_REST_HELPER,
        {
            "name": "Training coach weekly rest days",
            "min": 0,
            "max": 4,
            "step": 1,
            "initial": 1,
            "mode": "box",
            "icon": "mdi:bed",
        },
    ),
    (
        "input_select",
        FEELING_HELPER,
        {
            "name": "Training coach feeling",
            "options": list(FEELING_OPTIONS),
            "initial": "unset",
            "icon": "mdi:emoticon-outline",
        },
    ),
    (
        "input_select",
        DID_PLAN_HELPER,
        {
            "name": "Training coach did plan",
            "options": list(DID_PLAN_OPTIONS),
            "initial": "unset",
            "icon": "mdi:check-circle-outline",
        },
    ),
    (
        "input_select",
        SKIP_REASON_HELPER,
        {
            "name": "Training coach skip reason",
            "options": list(SKIP_REASON_OPTIONS),
            "initial": "unset",
            "icon": "mdi:help-circle-outline",
        },
    ),
]


class PrefsManager:
    def __init__(self, client: HomeAssistantClient, store: CoachStore) -> None:
        self.client = client
        self.store = store

    def ensure_helpers(self) -> None:
        missing = [
            (domain, entity_id, data)
            for domain, entity_id, data in HELPER_CREATE_SPECS
            if self.client.get_state(entity_id) is None
        ]
        if not missing:
            return
        session = None
        try:
            session = HaWebsocket(self.client.base_url, self.client.token)
            session.connect()
        except Exception as exc:  # noqa: BLE001
            _log(f"Helper websocket unavailable ({exc}); trying REST create")
            session = None
        try:
            for domain, entity_id, data in missing:
                try:
                    if session is not None:
                        result = session.command(f"{domain}/create", data)
                    else:
                        result = self.client.call_service(domain, "create", data)
                    created_id = result.get("id") if isinstance(result, dict) else None
                    created_eid = f"{domain}.{created_id}" if created_id else entity_id
                    if created_eid != entity_id:
                        _log(f"Created helper {created_eid} (expected {entity_id})")
                    else:
                        _log(f"Created helper {entity_id}")
                except Exception as exc:  # noqa: BLE001
                    _log(f"Could not create helper {entity_id}: {exc}")
        finally:
            if session is not None:
                session.close()

    def load_helper_states(self) -> dict[str, dict[str, Any]]:
        ids = [
            RACE_DATE_HELPER,
            RACE_DISTANCE_HELPER,
            TARGET_TIME_HELPER,
            WEEKLY_LONG_HELPER,
            WEEKLY_QUALITY_HELPER,
            WEEKLY_STRENGTH_HELPER,
            WEEKLY_REST_HELPER,
            FEELING_HELPER,
            DID_PLAN_HELPER,
            SKIP_REASON_HELPER,
        ]
        return self.client.get_states(ids)

    def current_prefs(self, today: date | None = None) -> Prefs:
        states = self.load_helper_states()
        if any(self.client.get_state(eid) is not None for eid in (
            RACE_DISTANCE_HELPER,
            WEEKLY_LONG_HELPER,
        )):
            prefs = prefs_from_states(states, today)
        else:
            stored = self.store.current_prefs()
            prefs = stored or Prefs.defaults()
        return prefs

    def sync_from_helpers(self, today: date | None = None) -> tuple[bool, Prefs]:
        """Persist helper values if the fingerprint changed. Returns (changed, prefs)."""
        prefs = self.current_prefs(today)
        current = self.store.current_prefs()
        if current is not None and current.fingerprint == prefs.fingerprint:
            return False, current
        stored = self.store.insert_prefs(prefs)
        _log(f"Prefs updated fingerprint={stored.fingerprint} source={stored.source}")
        return True, stored

    def apply_stdin(self, payload: dict[str, Any], today: date | None = None) -> Prefs:
        current = self.current_prefs(today)
        data = dict(current.as_dict())
        if "race_date" in payload:
            data["race_date"] = payload.get("race_date")
        if "race_distance" in payload:
            data["race_distance"] = payload.get("race_distance")
        if "target_time" in payload:
            data["target_time"] = payload.get("target_time") or ""
        for key in (
            "weekly_long_runs",
            "weekly_quality_runs",
            "weekly_strength",
            "weekly_rest_days",
        ):
            if key in payload:
                data[key] = payload[key]
        prefs = Prefs(
            race_date=parse_race_date(data.get("race_date"), today),
            race_distance=normalize_race_distance(str(data.get("race_distance") or "none")),
            target_time=str(data.get("target_time") or ""),
            weekly_long_runs=clamp_int(data.get("weekly_long_runs"), 1, 0, 3),
            weekly_quality_runs=clamp_int(data.get("weekly_quality_runs"), 1, 0, 4),
            weekly_strength=clamp_int(data.get("weekly_strength"), 2, 0, 5),
            weekly_rest_days=clamp_int(data.get("weekly_rest_days"), 1, 0, 4),
            source="stdin",
        )
        stored = self.store.insert_prefs(prefs)
        self.push_prefs_to_helpers(stored)
        return stored

    def push_prefs_to_helpers(self, prefs: Prefs) -> None:
        try:
            if prefs.race_date:
                self.client.call_service(
                    "input_datetime",
                    "set_datetime",
                    {"entity_id": RACE_DATE_HELPER, "date": prefs.race_date.isoformat()},
                )
            self.client.call_service(
                "input_select",
                "select_option",
                {"entity_id": RACE_DISTANCE_HELPER, "option": prefs.race_distance},
            )
            self.client.call_service(
                "input_text",
                "set_value",
                {"entity_id": TARGET_TIME_HELPER, "value": prefs.target_time},
            )
            for entity_id, value in (
                (WEEKLY_LONG_HELPER, prefs.weekly_long_runs),
                (WEEKLY_QUALITY_HELPER, prefs.weekly_quality_runs),
                (WEEKLY_STRENGTH_HELPER, prefs.weekly_strength),
                (WEEKLY_REST_HELPER, prefs.weekly_rest_days),
            ):
                self.client.call_service(
                    "input_number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                )
        except Exception as exc:  # noqa: BLE001
            _log(f"Could not push prefs to helpers: {exc}")

    def set_select(self, entity_id: str, option: str) -> None:
        try:
            self.client.call_service(
                "input_select",
                "select_option",
                {"entity_id": entity_id, "option": option},
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"Could not set {entity_id}={option}: {exc}")

    def reset_feedback_helpers(self) -> None:
        for entity_id in (FEELING_HELPER, DID_PLAN_HELPER, SKIP_REASON_HELPER):
            self.set_select(entity_id, "unset")
