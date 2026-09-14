"""Build a feature snapshot from Home Assistant states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from classify import (
    Session,
    classify_sport,
    is_training_session,
    session_day,
    session_from_strava_slot,
)
from entities import (
    GARMIN_BODY_BATTERY,
    GARMIN_HRV_BASELINE,
    GARMIN_HRV_NIGHT,
    GARMIN_HRV_STATUS,
    GARMIN_MORNING_READINESS,
    GARMIN_RECOVERY_TIME,
    GARMIN_SLEEP_SCORE,
    GARMIN_TRAINING_READINESS,
    OURA_HRV_BALANCE,
    OURA_LAST_WORKOUT_TYPE,
    OURA_READINESS,
    OURA_REST_MODE,
    OURA_SLEEP,
    OURA_SLEEP_HRV,
    OURA_TEMP,
    OURA_WORKOUTS_TODAY,
    STRAVA_LATEST_SPLITS,
    all_strava_slot_ids,
)
from parse import (
    attr,
    last_updated,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_duration_minutes,
    parse_float,
    state_value,
)
from settings import Settings
from splits import apply_splits_to_sessions, collect_split_sets


@dataclass
class Recovery:
    band: str
    rest_mode: bool
    oura_readiness: float | None
    oura_sleep: float | None
    oura_hrv: float | None
    oura_hrv_balance: float | None
    oura_temp: float | None
    garmin_readiness: float | None
    garmin_readiness_text: str | None
    garmin_body_battery: float | None
    garmin_recovery_hours: float | None
    garmin_hrv_status: str | None
    garmin_hrv_ratio: float | None
    reasons: list[str] = field(default_factory=list)


@dataclass
class FeatureSnapshot:
    now: datetime
    today: date
    recovery: Recovery
    sessions: list[Session]
    oura_synced_today: bool
    already_trained_today: bool


def _garmin_readiness_score(raw: Any) -> tuple[float | None, str | None]:
    text = None if raw is None else str(raw).strip()
    number = parse_float(raw)
    mapping = {
        "prime": 90.0,
        "productive": 80.0,
        "moderate": 65.0,
        "poor": 45.0,
        "unproductive": 40.0,
        "detraining": 50.0,
        "strained": 48.0,
        "recovery": 42.0,
    }
    if number is not None and number <= 10:
        # Some Garmin fields are 1-10 scores.
        number = number * 10
    if text:
        mapped = mapping.get(text.lower())
        if mapped is not None:
            return mapped, text
    return number, text


def score_recovery(states: dict[str, dict[str, Any]]) -> Recovery:
    rest_mode = parse_bool(state_value(states.get(OURA_REST_MODE))) or False
    oura_readiness = parse_float(state_value(states.get(OURA_READINESS)))
    oura_sleep = parse_float(state_value(states.get(OURA_SLEEP)))
    oura_hrv = parse_float(state_value(states.get(OURA_SLEEP_HRV)))
    oura_hrv_balance = parse_float(state_value(states.get(OURA_HRV_BALANCE)))
    oura_temp = parse_float(state_value(states.get(OURA_TEMP)))
    garmin_score, garmin_text = _garmin_readiness_score(
        state_value(states.get(GARMIN_TRAINING_READINESS))
        or state_value(states.get(GARMIN_MORNING_READINESS))
    )
    body_battery = parse_float(state_value(states.get(GARMIN_BODY_BATTERY)))
    recovery_raw = parse_float(state_value(states.get(GARMIN_RECOVERY_TIME)))
    recovery_hours = None
    if recovery_raw is not None:
        recovery_hours = recovery_raw / 60.0 if recovery_raw > 48 else recovery_raw
    hrv_status = state_value(states.get(GARMIN_HRV_STATUS))
    hrv_status_s = None if hrv_status is None else str(hrv_status)
    night = parse_float(state_value(states.get(GARMIN_HRV_NIGHT)))
    baseline = parse_float(state_value(states.get(GARMIN_HRV_BASELINE)))
    hrv_ratio = (night / baseline) if night and baseline else None

    poor_votes = 0
    good_votes = 0
    reasons: list[str] = []

    if rest_mode:
        poor_votes += 3
        reasons.append("Oura rest mode is on")

    def vote_score(name: str, value: float | None, poor_below: float, good_at: float) -> None:
        nonlocal poor_votes, good_votes
        if value is None:
            return
        if value < poor_below:
            poor_votes += 1
            reasons.append(f"{name} is low ({value:g})")
        elif value >= good_at:
            good_votes += 1

    vote_score("Oura readiness", oura_readiness, 60, 75)
    vote_score("Oura sleep", oura_sleep, 60, 75)
    garmin_sleep = parse_float(state_value(states.get(GARMIN_SLEEP_SCORE)))
    vote_score("Garmin sleep", garmin_sleep, 60, 75)
    vote_score("Garmin training readiness", garmin_score, 55, 75)
    vote_score("Body battery", body_battery, 30, 60)

    if oura_hrv_balance is not None and oura_hrv_balance < 70:
        poor_votes += 1
        reasons.append(f"HRV balance is low ({oura_hrv_balance:g})")
    elif oura_hrv_balance is not None and oura_hrv_balance >= 80:
        good_votes += 1

    if hrv_ratio is not None and hrv_ratio < 0.9:
        poor_votes += 1
        reasons.append(f"overnight HRV is below baseline ({hrv_ratio:.2f})")
    elif hrv_ratio is not None and hrv_ratio >= 1.0:
        good_votes += 1

    if hrv_status_s and hrv_status_s.lower() in {"unbalanced", "low", "poor"}:
        poor_votes += 1
        reasons.append(f"Garmin HRV status is {hrv_status_s}")

    if oura_temp is not None and abs(oura_temp) >= 0.5:
        poor_votes += 1
        reasons.append(f"temperature deviation is {oura_temp:g}°C")

    if recovery_hours is not None and recovery_hours >= 24:
        poor_votes += 1
        reasons.append(f"Garmin still wants {recovery_hours:.0f}h recovery")
    elif recovery_hours is not None and recovery_hours <= 8:
        good_votes += 1

    if rest_mode or poor_votes >= 2 or (oura_readiness is not None and oura_readiness < 55):
        band = "poor"
    elif good_votes >= 3 and poor_votes == 0 and (oura_readiness is None or oura_readiness >= 75):
        band = "good"
    elif poor_votes == 0 and (oura_readiness is None or oura_readiness >= 70) and good_votes >= 1:
        band = "good"
    else:
        band = "ok"

    if not reasons:
        reasons.append(f"recovery band is {band}")

    return Recovery(
        band=band,
        rest_mode=rest_mode,
        oura_readiness=oura_readiness,
        oura_sleep=oura_sleep,
        oura_hrv=oura_hrv,
        oura_hrv_balance=oura_hrv_balance,
        oura_temp=oura_temp,
        garmin_readiness=garmin_score,
        garmin_readiness_text=garmin_text,
        garmin_body_battery=body_battery,
        garmin_recovery_hours=recovery_hours,
        garmin_hrv_status=hrv_status_s,
        garmin_hrv_ratio=hrv_ratio,
        reasons=reasons,
    )


def collect_strava_sessions(
    states: dict[str, dict[str, Any]],
    settings: Settings,
) -> list[Session]:
    sessions: list[Session] = []
    seen: set[tuple] = set()
    for slot in all_strava_slot_ids(settings.strava_entity_prefix):
        session = session_from_strava_slot(
            states.get(slot.activity),
            states.get(slot.date),
            states.get(slot.distance),
            states.get(slot.moving_time),
            states.get(slot.elapsed_time),
            states.get(slot.average_heartrate),
            states.get(slot.max_heartrate),
            settings.tz,
            settings.long_run_min_minutes,
        )
        if not session:
            continue
        if session.activity_id:
            key: tuple = ("id", str(session.activity_id))
        else:
            key = (
                "t",
                session.title,
                session.when.isoformat() if session.when else None,
                round(session.duration_min or 0, 1),
                round(session.distance_m or 0, 0),
            )
        if key in seen:
            continue
        seen.add(key)
        sessions.append(session)
    return sessions


def merge_history_sessions(
    existing: list[Session],
    history: list[list[dict[str, Any]]],
    tz: ZoneInfo,
    long_run_min_minutes: int,
) -> list[Session]:
    """Use HA history of per-sport date sensors if a session rolled off the 10 slots."""
    from classify import STRENGTH, classify_sport

    known_dates = {s.when for s in existing if s.when}
    extra: list[Session] = []
    for series in history or []:
        if not series:
            continue
        entity_id = series[0].get("entity_id") or series[-1].get("entity_id") or ""
        sport = "Run" if "_run_" in entity_id else "WeightTraining" if "weight_training" in entity_id else ""
        if not sport:
            continue
        for point in series:
            when = parse_date(point.get("state"), tz)
            if not when or when in known_dates:
                continue
            session_type = classify_sport(sport, sport, None, None, None, long_run_min_minutes)
            extra.append(
                Session(
                    session_type=session_type if sport != "WeightTraining" else STRENGTH,
                    title=sport,
                    sport=sport,
                    when=when,
                    source="history",
                )
            )
            known_dates.add(when)
    return existing + extra


def _oura_item_is_training_today(
    item: dict[str, Any],
    tz: ZoneInfo,
    today: date,
    long_run_min_minutes: int,
) -> bool:
    """Oura auto-detects walks; those must not count as a logged training session."""
    activity = str(item.get("activity") or item.get("type") or "")
    when = parse_date(item.get("day") or item.get("start_datetime") or item.get("start"), tz)
    if when != today:
        return False
    start = parse_datetime(item.get("start_datetime") or item.get("start"), tz)
    end = parse_datetime(item.get("end_datetime") or item.get("end"), tz)
    duration = None
    if start and end:
        duration = max(0.0, (end - start).total_seconds() / 60.0)
    elif item.get("duration") is not None:
        duration = parse_duration_minutes(item.get("duration"))
    session_type = classify_sport(
        activity, activity, duration, None, None, long_run_min_minutes
    )
    return is_training_session(
        Session(session_type, activity, activity, when, duration_min=duration)
    )


def oura_structured_training_today(
    states: dict[str, dict[str, Any]],
    tz: ZoneInfo,
    today: date,
    long_run_min_minutes: int,
) -> bool:
    """True only if Oura logged a structured workout *today* (not a walk / stale count)."""
    workouts = attr(states.get(OURA_WORKOUTS_TODAY), "workouts") or []
    if isinstance(workouts, list) and workouts:
        return any(
            isinstance(item, dict)
            and _oura_item_is_training_today(item, tz, today, long_run_min_minutes)
            for item in workouts
        )
    raw = attr(states.get(OURA_LAST_WORKOUT_TYPE), "workout") or {}
    if not isinstance(raw, dict) or not raw:
        return False
    activity = raw.get("activity") or state_value(states.get(OURA_LAST_WORKOUT_TYPE))
    return _oura_item_is_training_today(
        {**raw, "activity": activity},
        tz,
        today,
        long_run_min_minutes,
    )


def already_trained_on(sessions: list[Session], day: date) -> bool:
    return any(session_day(s) == day and is_training_session(s) for s in sessions)


def oura_is_synced_today(states: dict[str, dict[str, Any]], tz: ZoneInfo, today: date) -> bool:
    updated = last_updated(states.get(OURA_READINESS), tz)
    if updated and updated.date() == today:
        return True
    sleep_updated = last_updated(states.get(OURA_SLEEP), tz)
    return bool(sleep_updated and sleep_updated.date() == today)


def collect_live_sessions(
    states: dict[str, dict[str, Any]],
    settings: Settings,
    history: list[list[dict[str, Any]]] | None = None,
    split_history: list[list[dict[str, Any]]] | None = None,
) -> list[Session]:
    """Classify sessions from current HA states (and optional one-shot history seed)."""
    sessions = collect_strava_sessions(states, settings)
    if history:
        sessions = merge_history_sessions(
            sessions, history, settings.tz, settings.long_run_min_minutes
        )
    split_sets = collect_split_sets(
        states.get(STRAVA_LATEST_SPLITS),
        split_history,
        settings.tz,
    )
    if split_sets:
        sessions = apply_splits_to_sessions(sessions, split_sets, settings.long_run_min_minutes)
    return sessions


def build_snapshot(
    states: dict[str, dict[str, Any]],
    settings: Settings,
    now: datetime | None = None,
    history: list[list[dict[str, Any]]] | None = None,
    split_history: list[list[dict[str, Any]]] | None = None,
    sessions: list[Session] | None = None,
) -> FeatureSnapshot:
    now = now or datetime.now(settings.tz)
    today = now.date()
    recovery = score_recovery(states)
    if sessions is None:
        sessions = collect_live_sessions(states, settings, history, split_history)
    already = already_trained_on(sessions, today) or oura_structured_training_today(
        states, settings.tz, today, settings.long_run_min_minutes
    )
    sessions = sorted(sessions, key=lambda s: s.when or date.min, reverse=True)
    return FeatureSnapshot(
        now=now,
        today=today,
        recovery=recovery,
        sessions=sessions,
        oura_synced_today=oura_is_synced_today(states, settings.tz, today),
        already_trained_today=already,
    )


def sessions_since(snapshot: FeatureSnapshot, start: date) -> list[Session]:
    out: list[Session] = []
    for session in snapshot.sessions:
        when = session_day(session)
        if when and when >= start:
            out.append(session)
    return out


def yesterday_session(snapshot: FeatureSnapshot) -> Session | None:
    target = snapshot.today - timedelta(days=1)
    for session in snapshot.sessions:
        if session_day(session) == target and is_training_session(session):
            return session
    return None
