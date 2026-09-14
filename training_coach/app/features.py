"""Build a feature snapshot from Home Assistant states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from classify import (
    Session,
    is_training_session,
    merge_training_sessions,
    session_day,
    session_from_garmin_activity,
    session_from_garmin_entity,
    session_from_strava_slot,
)
from entities import (
    GARMIN_ACTIVE_CALORIES,
    GARMIN_ACTIVE_CALORIES_FALLBACK,
    GARMIN_BODY_BATTERY,
    GARMIN_HRV_BASELINE,
    GARMIN_HRV_NIGHT,
    GARMIN_HRV_STATUS,
    GARMIN_INTENSITY_MINUTES,
    GARMIN_INTENSITY_MINUTES_FALLBACK,
    GARMIN_LAST_ACTIVITIES,
    GARMIN_LAST_ACTIVITIES_FALLBACK,
    GARMIN_LAST_ACTIVITY,
    GARMIN_LAST_ACTIVITY_FALLBACK,
    GARMIN_MORNING_READINESS,
    GARMIN_RECOVERY_TIME,
    GARMIN_SLEEP_SCORE,
    GARMIN_TOTAL_STEPS,
    GARMIN_TOTAL_STEPS_FALLBACK,
    GARMIN_TRAINING_READINESS,
    GARMIN_YESTERDAY_STEPS,
    OURA_ACTIVE_CALORIES,
    OURA_ACTIVITY_SCORE,
    OURA_HIGH_ACTIVITY_TIME,
    OURA_HRV_BALANCE,
    OURA_MEDIUM_ACTIVITY_TIME,
    OURA_READINESS,
    OURA_REST_MODE,
    OURA_SLEEP,
    OURA_SLEEP_HRV,
    OURA_STEPS,
    OURA_TEMP,
    STRAVA_LATEST_SPLITS,
    all_strava_slot_ids,
)
from parse import (
    attr,
    first_entity,
    last_updated,
    parse_bool,
    parse_date,
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
class DayActivity:
    """Fused daily movement (NEAT), not sport sessions.

    Oura workouts are ignored. Steps/calories/intensity come from Oura Activity
    plus Garmin daily totals so a rest-day walk still shows up as load.
    """

    oura_score: float | None = None
    oura_steps: float | None = None
    oura_active_kcal: float | None = None
    oura_high_min: float | None = None
    oura_medium_min: float | None = None
    garmin_steps: float | None = None
    garmin_yesterday_steps: float | None = None
    garmin_active_kcal: float | None = None
    garmin_intensity_min: float | None = None
    steps: float | None = None
    yesterday_steps: float | None = None
    active_kcal: float | None = None
    intensity_min: float | None = None

    @property
    def insight_steps(self) -> float | None:
        """Yesterday's Garmin steps when present; otherwise today's fused steps."""
        if self.yesterday_steps is not None:
            return self.yesterday_steps
        return self.steps

    def as_dict(self) -> dict[str, float | None]:
        return {
            "oura_score": self.oura_score,
            "oura_steps": self.oura_steps,
            "oura_active_kcal": self.oura_active_kcal,
            "garmin_steps": self.garmin_steps,
            "garmin_yesterday_steps": self.garmin_yesterday_steps,
            "garmin_active_kcal": self.garmin_active_kcal,
            "garmin_intensity_min": self.garmin_intensity_min,
            "steps": self.steps,
            "yesterday_steps": self.yesterday_steps,
            "active_kcal": self.active_kcal,
            "intensity_min": self.intensity_min,
            "insight_steps": self.insight_steps,
        }


@dataclass
class FeatureSnapshot:
    now: datetime
    today: date
    recovery: Recovery
    sessions: list[Session]
    oura_synced_today: bool
    already_trained_today: bool
    activity: DayActivity = field(default_factory=DayActivity)


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
    seen: set[tuple[str, str | None]] = set()
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
        key = (session.title, session.when.isoformat() if session.when else None)
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
    return merge_training_sessions(existing, extra)


def collect_garmin_sessions(
    states: dict[str, dict[str, Any]],
    settings: Settings,
) -> list[Session]:
    """Completed Garmin activities only — planned `last_workout` is ignored."""
    sessions: list[Session] = []
    seen: set[str] = set()
    activities_entity = first_entity(
        states, GARMIN_LAST_ACTIVITIES, GARMIN_LAST_ACTIVITIES_FALLBACK
    )
    raw_list = attr(activities_entity, "last_activities") or attr(activities_entity, "activities") or []
    if isinstance(raw_list, list):
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            session = session_from_garmin_activity(
                item, settings.tz, settings.long_run_min_minutes
            )
            if not session:
                continue
            if session.activity_id:
                if session.activity_id in seen:
                    continue
                seen.add(session.activity_id)
            sessions.append(session)
    last = session_from_garmin_entity(
        first_entity(states, GARMIN_LAST_ACTIVITY, GARMIN_LAST_ACTIVITY_FALLBACK),
        settings.tz,
        settings.long_run_min_minutes,
    )
    if last and (not last.activity_id or last.activity_id not in seen):
        sessions.append(last)
    return sessions


def _max_num(*values: float | None) -> float | None:
    nums = [value for value in values if value is not None]
    return max(nums) if nums else None


def collect_day_activity(states: dict[str, dict[str, Any]]) -> DayActivity:
    """Oura daily Activity + Garmin totals. Does not use Oura sport workouts."""
    oura_score = parse_float(state_value(states.get(OURA_ACTIVITY_SCORE)))
    oura_steps = parse_float(state_value(states.get(OURA_STEPS)))
    oura_kcal = parse_float(state_value(states.get(OURA_ACTIVE_CALORIES)))
    oura_high = parse_float(state_value(states.get(OURA_HIGH_ACTIVITY_TIME)))
    oura_medium = parse_float(state_value(states.get(OURA_MEDIUM_ACTIVITY_TIME)))
    garmin_steps = parse_float(
        state_value(first_entity(states, GARMIN_TOTAL_STEPS, GARMIN_TOTAL_STEPS_FALLBACK))
    )
    garmin_yesterday = parse_float(state_value(first_entity(states, GARMIN_YESTERDAY_STEPS)))
    garmin_kcal = parse_float(
        state_value(first_entity(states, GARMIN_ACTIVE_CALORIES, GARMIN_ACTIVE_CALORIES_FALLBACK))
    )
    garmin_intensity = parse_float(
        state_value(
            first_entity(states, GARMIN_INTENSITY_MINUTES, GARMIN_INTENSITY_MINUTES_FALLBACK)
        )
    )
    oura_intensity = None
    if oura_high is not None or oura_medium is not None:
        oura_intensity = (oura_high or 0.0) + (oura_medium or 0.0)
    return DayActivity(
        oura_score=oura_score,
        oura_steps=oura_steps,
        oura_active_kcal=oura_kcal,
        oura_high_min=oura_high,
        oura_medium_min=oura_medium,
        garmin_steps=garmin_steps,
        garmin_yesterday_steps=garmin_yesterday,
        garmin_active_kcal=garmin_kcal,
        garmin_intensity_min=garmin_intensity,
        steps=_max_num(oura_steps, garmin_steps),
        yesterday_steps=garmin_yesterday,
        active_kcal=_max_num(oura_kcal, garmin_kcal),
        intensity_min=_max_num(garmin_intensity, oura_intensity),
    )


def add_activity_reasons(recovery: Recovery, activity: DayActivity) -> None:
    """Note high NEAT on the recovery snapshot; does not change the band."""
    steps = activity.insight_steps
    if steps is not None and steps >= 12000:
        recovery.reasons.append(f"day activity is {steps / 1000.0:.1f}k steps")
    elif activity.intensity_min is not None and activity.intensity_min >= 45:
        recovery.reasons.append(f"day activity is {activity.intensity_min:.0f} intensity min")


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
    """Classify sport sessions from Strava and Garmin (never Oura workouts)."""
    sessions = collect_strava_sessions(states, settings)
    garmin = collect_garmin_sessions(states, settings)
    sessions = merge_training_sessions(sessions, garmin)
    if history:
        sessions = merge_history_sessions(
            sessions, history, settings.tz, settings.long_run_min_minutes
        )
        sessions = merge_training_sessions(sessions)
    split_sets = collect_split_sets(
        states.get(STRAVA_LATEST_SPLITS),
        split_history,
        settings.tz,
    )
    if split_sets:
        sessions = apply_splits_to_sessions(sessions, split_sets, settings.long_run_min_minutes)
        sessions = merge_training_sessions(sessions)
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
    activity = collect_day_activity(states)
    add_activity_reasons(recovery, activity)
    if sessions is None:
        sessions = collect_live_sessions(states, settings, history, split_history)
    else:
        sessions = merge_training_sessions(sessions)
    already = already_trained_on(sessions, today)
    sessions = sorted(sessions, key=lambda s: s.when or date.min, reverse=True)
    return FeatureSnapshot(
        now=now,
        today=today,
        recovery=recovery,
        sessions=sessions,
        oura_synced_today=oura_is_synced_today(states, settings.tz, today),
        already_trained_today=already,
        activity=activity,
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
