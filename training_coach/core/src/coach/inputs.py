"""Normalize API and app payloads into the types the rules already use.

Home Assistant sensor dictionaries stay in ``features`` and ``entities``.
Callers that already have scores and activities use this module.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from coach.classify import (
    OTHER,
    Session,
    classify_logged_session,
    reference_max_hr,
)
from coach.entities import (
    GARMIN_BODY_BATTERY,
    GARMIN_HRV_BASELINE,
    GARMIN_HRV_NIGHT,
    GARMIN_HRV_STATUS,
    GARMIN_MORNING_READINESS,
    GARMIN_RECOVERY_TIME,
    GARMIN_SLEEP_SCORE,
    OURA_HRV_BALANCE,
    OURA_READINESS,
    OURA_REST_MODE,
    OURA_SLEEP,
    OURA_SLEEP_HRV,
    OURA_TEMP,
)
from coach.features import (
    DayActivity,
    Recovery,
    add_activity_reasons,
    garmin_is_awake,
    score_recovery,
)
from coach.goal import (
    WEEKDAY_KEYS,
    Prefs,
    clamp_int,
    normalize_race_distance,
    parse_race_date,
)
from coach.load import session_load
from coach.settings import Settings

# Filled only when that score was omitted, so an explicit number always wins.
FEEL_DEFAULTS = {
    "poor": {"oura_readiness": 48, "oura_sleep": 50},
    "ok": {"oura_readiness": 68, "oura_sleep": 68},
    "good": {"oura_readiness": 82, "oura_sleep": 80},
}

ACTIVITY_FIELDS = (
    "steps",
    "yesterday_steps",
    "active_kcal",
    "intensity_min",
    "oura_score",
    "oura_steps",
    "oura_active_kcal",
    "oura_high_min",
    "oura_medium_min",
    "garmin_steps",
    "garmin_yesterday_steps",
    "garmin_active_kcal",
    "garmin_intensity_min",
)

# Keys recovery_from_signals reads. Add a key here when that function reads a new one.
RECOVERY_FIELDS = (
    "feel",
    "oura_readiness",
    "oura_sleep",
    "oura_hrv",
    "oura_hrv_balance",
    "oura_temp",
    "rest_mode",
    "garmin_awake",
    "garmin_readiness",
    "garmin_sleep",
    "garmin_body_battery",
    "garmin_recovery_hours",
    "garmin_hrv_status",
    "garmin_hrv_night",
    "garmin_hrv_baseline",
)


def prefs_from_dict(data: dict | None) -> Prefs:
    data = data or {}
    race_raw = data.get("race_date")
    race_date = race_raw if isinstance(race_raw, date) else parse_race_date(
        None if race_raw is None else str(race_raw)
    )
    return Prefs(
        race_date=race_date,
        race_distance=normalize_race_distance(data.get("race_distance")),
        target_time=str(data.get("target_time") or ""),
        weekly_long_runs=clamp_int(data.get("weekly_long_runs"), 1, 0, 3),
        weekly_quality_runs=clamp_int(data.get("weekly_quality_runs"), 1, 0, 4),
        weekly_strength=clamp_int(data.get("weekly_strength"), 2, 0, 5),
        weekly_rest_days=clamp_int(data.get("weekly_rest_days"), 1, 0, 4),
        source=str(data.get("source") or "api"),
    )


def normalize_locks(locks: dict | None) -> dict[int, str]:
    from coach.goal import LOCK_TYPES, parse_lock_updates

    if not locks:
        return {}
    incoming: dict[str, str] = {}
    direct: dict[int, str] = {}
    for key, value in locks.items():
        if value in (None, "", "unset"):
            if isinstance(key, str):
                incoming[key] = "unset"
            continue
        if isinstance(key, int):
            if value in LOCK_TYPES:
                direct[key] = str(value)
            continue
        incoming[str(key)] = str(value)
    parsed = parse_lock_updates(incoming) if incoming else {}
    for weekday, kind in parsed.items():
        if kind:
            direct[weekday] = kind
    return direct


def locks_to_public(locks: dict[int, str] | None) -> dict[str, str]:
    return {WEEKDAY_KEYS[day]: kind for day, kind in sorted((locks or {}).items()) if kind}


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_when(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_started(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def session_from_row(
    data: dict,
    *,
    long_run_min_minutes: int,
    hr_max: float | None,
) -> Session:
    when = _parse_when(data.get("when"))
    started = _parse_started(data.get("started_at"))
    if when is None and started is not None:
        when = started.date()
    elif when is not None and started is not None and started.date() != when:
        started = started.replace(year=when.year, month=when.month, day=when.day)
    distance_m = _number(data.get("distance_m"))
    if distance_m is None and data.get("distance_km") is not None:
        distance_m = _number(data.get("distance_km")) * 1000.0
    locked = bool(data.get("type_locked"))
    explicit = data.get("session_type")
    session = Session(
        session_type=str(explicit) if locked and explicit else OTHER,
        title=str(data.get("title") or ""),
        sport=str(data.get("sport") or ""),
        when=when,
        duration_min=_number(data.get("duration_min")),
        distance_m=distance_m,
        avg_hr=_number(data.get("avg_hr")),
        max_hr=_number(data.get("max_hr")),
        source=str(data.get("source") or "manual"),
        activity_id=None if data.get("activity_id") is None else str(data.get("activity_id")),
        started_at=started,
        relative_effort=_number(data.get("relative_effort")),
        splits=data.get("splits"),
        laps=data.get("laps"),
    )
    if not locked:
        session.session_type = classify_logged_session(
            session, long_run_min_minutes, hr_max
        )
    session.session_load = session_load(session)
    return session


def prepare_sessions(
    rows: list[dict] | None,
    settings: Settings,
    today: date,
) -> list[tuple[dict, Session]]:
    rows = list(rows or [])
    bare = [
        session_from_row(
            row,
            long_run_min_minutes=settings.long_run_min_minutes,
            hr_max=None,
        )
        for row in rows
    ]
    hr_max, _source = reference_max_hr(bare, today, float(settings.max_heart_rate))
    prepared = [
        session_from_row(
            row,
            long_run_min_minutes=settings.long_run_min_minutes,
            hr_max=hr_max,
        )
        for row in rows
    ]
    return list(zip(rows, prepared))


def session_to_dict(session: Session, row: dict | None = None) -> dict:
    row = row or {}
    return {
        "id": row.get("id") or getattr(session, "row_id", None),
        "session_type": session.session_type,
        "title": session.title,
        "sport": session.sport,
        "when": session.when.isoformat() if session.when else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "duration_min": session.duration_min,
        "distance_m": session.distance_m,
        "distance_km": None if session.distance_m is None else round(session.distance_m / 1000.0, 3),
        "avg_hr": session.avg_hr,
        "max_hr": session.max_hr,
        "source": session.source,
        "activity_id": session.activity_id,
        "relative_effort": session.relative_effort,
        "session_load": None if session.session_load is None else round(session.session_load, 1),
        "type_locked": bool(row.get("type_locked")),
    }


def _with_feel(payload: dict) -> dict:
    data = dict(payload or {})
    feel = str(data.get("feel") or "").strip().lower()
    defaults = FEEL_DEFAULTS.get(feel)
    if not defaults:
        return data
    for key, value in defaults.items():
        if data.get(key) is None:
            data[key] = value
    return data


def _entity(state, stamp: str, **attrs) -> dict:
    return {
        "state": "" if state is None else str(state),
        "attributes": attrs,
        "last_updated": stamp,
        "last_changed": stamp,
    }


def recovery_from_signals(
    payload: dict | None,
    today: date,
    tz: ZoneInfo,
) -> tuple[Recovery, bool, bool]:
    """Score recovery from plain numbers.

    Returns the recovery row, whether Garmin is awake, and whether Oura
    scores for today were present (including a feel shortcut).
    """
    data = _with_feel(payload or {})
    awake_requested = bool(data.get("garmin_awake"))
    stamp = datetime.combine(today, time(7, 30), tzinfo=tz).isoformat()
    states: dict[str, dict] = {}

    def put(key: str, value) -> None:
        if value is None or value == "":
            return
        states[key] = _entity(value, stamp)

    put(OURA_READINESS, data.get("oura_readiness"))
    put(OURA_SLEEP, data.get("oura_sleep"))
    put(OURA_SLEEP_HRV, data.get("oura_hrv"))
    put(OURA_HRV_BALANCE, data.get("oura_hrv_balance"))
    put(OURA_TEMP, data.get("oura_temp"))
    if data.get("rest_mode"):
        states[OURA_REST_MODE] = _entity("on", stamp)
    elif "rest_mode" in data:
        states[OURA_REST_MODE] = _entity("off", stamp)
    if awake_requested:
        put(GARMIN_MORNING_READINESS, data.get("garmin_readiness"))
        if data.get("garmin_readiness") is not None:
            states[GARMIN_MORNING_READINESS]["attributes"]["calendarDate"] = today.isoformat()
            if data.get("garmin_sleep") is not None:
                states[GARMIN_MORNING_READINESS]["attributes"]["sleep_score"] = data.get("garmin_sleep")
        put(GARMIN_SLEEP_SCORE, data.get("garmin_sleep"))
        put(GARMIN_BODY_BATTERY, data.get("garmin_body_battery"))
        put(GARMIN_RECOVERY_TIME, data.get("garmin_recovery_hours"))
        if GARMIN_RECOVERY_TIME in states:
            states[GARMIN_RECOVERY_TIME]["attributes"]["unit_of_measurement"] = "h"
        put(GARMIN_HRV_STATUS, data.get("garmin_hrv_status"))
        put(GARMIN_HRV_NIGHT, data.get("garmin_hrv_night"))
        put(GARMIN_HRV_BASELINE, data.get("garmin_hrv_baseline"))
    recovery = score_recovery(states, tz, today)
    awake = awake_requested and garmin_is_awake(states, tz, today)
    oura_synced = any(
        data.get(key) is not None
        for key in ("oura_readiness", "oura_sleep", "oura_hrv", "oura_hrv_balance", "feel")
    )
    return recovery, awake, oura_synced


def activity_from_payload(payload: dict | None) -> DayActivity:
    """Day movement from Oura and Garmin fields.

    When the fused totals are omitted, steps, calories, and intensity use the
    higher of the two sources, matching the Home Assistant snapshot.
    """
    data = payload or {}
    values = {key: _number(data.get(key)) for key in ACTIVITY_FIELDS}
    activity = DayActivity(**values)
    if activity.steps is None:
        activity.steps = _max_present(activity.oura_steps, activity.garmin_steps)
    if activity.yesterday_steps is None:
        activity.yesterday_steps = activity.garmin_yesterday_steps
    if activity.active_kcal is None:
        activity.active_kcal = _max_present(activity.oura_active_kcal, activity.garmin_active_kcal)
    if activity.intensity_min is None:
        oura_intensity = None
        if activity.oura_high_min is not None or activity.oura_medium_min is not None:
            oura_intensity = (activity.oura_high_min or 0.0) + (activity.oura_medium_min or 0.0)
        activity.intensity_min = _max_present(activity.garmin_intensity_min, oura_intensity)
    return activity


def _max_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def apply_activity(recovery: Recovery, activity: DayActivity) -> None:
    add_activity_reasons(recovery, activity)
