"""Morning plan and evening recap.

Vendor HTTP stays in the API integrations. This module only sees sessions,
recovery scores, and day activity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from coach.classify import merge_training_sessions
from coach.features import FeatureSnapshot, already_trained_on
from coach.feedback import (
    COMPLIANCE_MATCH,
    COMPLIANCE_SKIPPED,
    DID_SESSION_COMPLIANCE,
    classify_compliance,
    describe_evening_tomorrow,
    format_logged_label,
    logged_sessions,
    recap_text,
)
from coach.goal import (
    DID_PLAN_OPTIONS,
    EFFORT_FIT_OPTIONS,
    FEELING_OPTIONS,
    SKIP_REASON_OPTIONS,
    Prefs,
    days_to_race,
    format_hms,
    phase_for,
)
from coach.inputs import (
    ACTIVITY_FIELDS,
    activity_from_payload,
    apply_activity,
    locks_to_public,
    normalize_locks,
    prefs_from_dict,
    prepare_sessions,
    recovery_from_signals,
    session_to_dict,
)
from coach.load import LoadSnapshot, build_load_snapshot
from coach.messages import format_morning_message
from coach.paces import PaceSet, build_paces, format_pace_range
from coach.periodize import PlanDay, build_skeleton
from coach.planner import Plan, ease_stacked_tomorrow, plan_day
from coach.recipes import format_km_range
from coach.settings import Settings
from coach.simulate import finish_distribution, search_calendar


@dataclass
class MorningResult:
    plan: Plan
    calendar: list[PlanDay]
    load: LoadSnapshot
    paces: PaceSet
    prediction: dict
    phase: str | None
    snapshot: FeatureSnapshot
    settings: Settings
    prefs: Prefs
    locks: dict[int, str]
    sessions: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        phase = self.phase
        goal = dict(self.prefs.as_dict())
        goal["days_to_race"] = days_to_race(self.snapshot.today, self.prefs.race_date)
        goal["phase"] = phase
        return {
            "today": self.snapshot.today.isoformat(),
            "timezone": self.settings.timezone,
            "phase": phase,
            "plan": _plan_dict(self.plan),
            "morning_message": format_morning_message(
                self.plan, weekly_load=self.load.weekly_load
            ),
            "calendar": [_plan_day_dict(day) for day in self.calendar],
            "load": _load_dict(self.load),
            "paces": self.paces.as_dict(),
            "prediction": _prediction_dict(self.prediction),
            "recovery": asdict(self.snapshot.recovery),
            "activity": self.snapshot.activity.as_dict(),
            "already_trained_today": self.snapshot.already_trained_today,
            "garmin_awake": self.snapshot.garmin_awake,
            "oura_synced_today": self.snapshot.oura_synced_today,
            "prefs": goal,
            "locks": locks_to_public(self.locks),
            "sessions": self.sessions,
        }


@dataclass
class EveningResult:
    compliance: str
    message: str
    planned_type: str | None
    planned_title: str
    actual_types: list[str]
    tomorrow: str | None
    logged_label: str
    checkin: dict
    feedback: dict

    def as_dict(self) -> dict:
        return {
            "compliance": self.compliance,
            "message": self.message,
            "planned_type": self.planned_type,
            "planned_title": self.planned_title,
            "actual_types": self.actual_types,
            "tomorrow": self.tomorrow,
            "logged_label": self.logged_label,
            "checkin": self.checkin,
            "feedback": self.feedback,
        }


def plan_from_payload(
    *,
    today: date,
    timezone: str,
    recovery: dict | None = None,
    activity: dict | None = None,
    sessions: list[dict] | None = None,
    prefs: dict | None = None,
    locks: dict | None = None,
    feedback: list[dict] | None = None,
    max_heart_rate: int = 190,
    long_run_min_minutes: int = 75,
    now: datetime | None = None,
) -> MorningResult:
    settings = Settings(
        timezone=timezone,
        max_heart_rate=max_heart_rate,
        long_run_min_minutes=long_run_min_minutes,
    )
    prefs_obj = prefs_from_dict(prefs)
    lock_map = normalize_locks(locks)
    pairs = prepare_sessions(sessions, settings, today)
    prepared = []
    for row, session in pairs:
        session.row_id = row.get("id")  # type: ignore[attr-defined]
        prepared.append(session)
    merged = merge_training_sessions(prepared)
    snapshot = _snapshot(
        today=today,
        timezone=timezone,
        sessions=merged,
        recovery=recovery,
        activity=_activity_payload(recovery, activity),
        now=now,
    )
    result = plan_morning(
        snapshot,
        prefs_obj,
        lock_map,
        _normalize_feedback(feedback),
        settings,
    )
    result.sessions = [session_to_dict(session) for session in merged]
    for raw, published in zip(merged, result.sessions):
        published["id"] = getattr(raw, "row_id", None)
    return result


def plan_morning(
    snapshot: FeatureSnapshot,
    prefs: Prefs | None = None,
    locks: dict[int, str] | None = None,
    feedback: list[dict] | None = None,
    settings: Settings | None = None,
) -> MorningResult:
    settings = settings or Settings()
    prefs = prefs or Prefs.defaults()
    locks = locks or {}
    feedback = feedback or []
    yesterday = _feedback_on(feedback, snapshot.today - timedelta(days=1))
    feeling = yesterday.get("feeling")
    last_compliance = _last_quality_compliance(snapshot, feedback)
    load = build_load_snapshot(snapshot.sessions, snapshot.today)
    paces = build_paces(snapshot.sessions, prefs, snapshot.today)
    skeleton = build_skeleton(
        snapshot.today,
        prefs,
        load,
        paces,
        snapshot.sessions,
        feeling,
        last_compliance,
        locks,
    )
    finish = finish_distribution(
        paces, prefs, seed=int(prefs.fingerprint[:8], 16) % 100000
    )
    calendar = search_calendar(skeleton, load, prefs, paces, feedback, finish)
    today_row = next((day for day in calendar if day.day == snapshot.today), None)
    if today_row is not None and not (prefs.has_race or today_row.source == "lock"):
        today_row = None
    upcoming = _upcoming(calendar, snapshot.today)
    phase = today_row.phase if today_row else phase_for(snapshot.today, prefs)
    goal = {
        **prefs.as_dict(),
        "days_to_race": days_to_race(snapshot.today, prefs.race_date),
        "phase": phase,
        **{key: finish.get(key) for key in ("p10", "p50", "p90", "p_hit", "feasible")},
    }
    plan = plan_day(
        snapshot,
        settings,
        prefs=prefs,
        calendar_today=today_row,
        upcoming=upcoming,
        prediction=finish,
        goal=goal,
        paces=paces,
        locks=locks,
    )
    if ease_stacked_tomorrow(calendar, snapshot.today, plan.session_type, load, paces):
        plan.upcoming = _upcoming(calendar, snapshot.today)
    return MorningResult(
        plan=plan,
        calendar=calendar,
        load=load,
        paces=paces,
        prediction=finish,
        phase=phase,
        snapshot=snapshot,
        settings=settings,
        prefs=prefs,
        locks=locks,
    )


def evening_from_payload(
    *,
    today: date,
    timezone: str,
    decision: dict,
    sessions: list[dict] | None = None,
    calendar: list[dict] | None = None,
    recovery: dict | None = None,
    activity: dict | None = None,
    max_heart_rate: int = 190,
    long_run_min_minutes: int = 75,
) -> EveningResult:
    settings = Settings(
        timezone=timezone,
        max_heart_rate=max_heart_rate,
        long_run_min_minutes=long_run_min_minutes,
    )
    pairs = prepare_sessions(sessions, settings, today)
    prepared = [session for _row, session in pairs]
    merged = merge_training_sessions(prepared)
    snapshot = _snapshot(
        today=today,
        timezone=timezone,
        sessions=merged,
        recovery=recovery,
        activity=activity,
    )
    load = build_load_snapshot(merged, today)
    planned_type = decision.get("session_type")
    recipe = decision.get("recipe") or {}
    planned_title = decision.get("title") or recipe.get("title") or "No morning plan"
    today_sessions = logged_sessions(merged, today)
    actuals = [session.session_type for session in today_sessions]
    actual = actuals[0] if actuals else None
    extras = [kind for kind in actuals if kind != planned_type]
    compliance = classify_compliance(planned_type, actual, actuals=actuals)
    tomorrow_row = _tomorrow_row(today, decision.get("upcoming"), calendar)
    tomorrow_text = describe_evening_tomorrow(tomorrow_row, today_sessions)
    message = recap_text(
        planned_title,
        planned_type,
        actual,
        compliance,
        ask_helpers=False,
        tomorrow=tomorrow_text,
        logged_label=format_logged_label(today_sessions),
        extras=extras,
        logged_count=len(today_sessions),
        activity=snapshot.activity,
        daily_load=load.daily_load,
        weekly_load=load.weekly_load,
    )
    relevant = ["feeling"]
    if compliance != COMPLIANCE_MATCH:
        relevant.append("did_plan")
    if compliance == COMPLIANCE_SKIPPED:
        relevant.append("skip_reason")
    if compliance in DID_SESSION_COMPLIANCE:
        relevant.append("effort_fit")
    return EveningResult(
        compliance=compliance,
        message=message,
        planned_type=planned_type,
        planned_title=planned_title,
        actual_types=actuals,
        tomorrow=tomorrow_text,
        logged_label=format_logged_label(today_sessions),
        checkin={
            "relevant": relevant,
            "feeling": list(FEELING_OPTIONS),
            "did_plan": list(DID_PLAN_OPTIONS),
            "skip_reason": list(SKIP_REASON_OPTIONS),
            "effort_fit": list(EFFORT_FIT_OPTIONS),
        },
        feedback={
            "day": today.isoformat(),
            "planned_type": planned_type,
            "actual_type": ",".join(actuals) if actuals else actual,
            "compliance": compliance,
            "recovery_band": decision.get("recovery_band") or snapshot.recovery.band,
            "source": "evening",
        },
    )


def _snapshot(
    *,
    today: date,
    timezone: str,
    sessions,
    recovery: dict | None,
    activity: dict | None,
    now: datetime | None = None,
) -> FeatureSnapshot:
    tz = ZoneInfo(timezone)
    now = now or datetime.combine(today, time(7, 30), tzinfo=tz)
    scored, awake, synced = recovery_from_signals(recovery, today, tz)
    day_activity = activity_from_payload(activity)
    apply_activity(scored, day_activity)
    return FeatureSnapshot(
        now=now,
        today=today,
        recovery=scored,
        sessions=list(sessions),
        oura_synced_today=synced,
        already_trained_today=already_trained_on(sessions, today),
        garmin_awake=awake,
        activity=day_activity,
    )


def _activity_payload(recovery: dict | None, activity: dict | None) -> dict | None:
    if activity is not None:
        return activity
    if not recovery:
        return None
    picked = {key: recovery[key] for key in ACTIVITY_FIELDS if key in recovery}
    return picked or None


def _normalize_feedback(rows: list[dict] | None) -> list[dict]:
    out = []
    for row in rows or []:
        item = dict(row)
        day = item.get("day")
        if isinstance(day, str) and day:
            item["day"] = date.fromisoformat(day[:10])
        out.append(item)
    return out


def _feedback_on(rows: list[dict], day: date) -> dict:
    found = [row for row in rows if row.get("day") == day]
    return found[-1] if found else {}


def _last_quality_compliance(snapshot: FeatureSnapshot, feedback: list[dict]) -> str | None:
    for session in sorted(
        snapshot.sessions, key=lambda item: item.when or date.min, reverse=True
    ):
        if session.session_type in {"intervals", "tempo"} and session.when:
            row = _feedback_on(feedback, session.when)
            return row.get("compliance")
    return None


def _upcoming(days: list[PlanDay], today: date, limit: int = 7) -> list[dict]:
    out = []
    for item in days:
        if item.day <= today:
            continue
        published = _plan_day_dict(item)
        pace = published["pace"]
        published["line"] = (
            f"{item.day.strftime('%a')}: {item.session_type.replace('_', ' ')} "
            f"{published['km']}"
            + (f" @ {pace}" if pace else "")
        ).strip()
        out.append(published)
        if len(out) >= limit:
            break
    return out


def _plan_day_dict(day: PlanDay) -> dict:
    raw = day.as_dict()
    raw["day"] = day.day.isoformat()
    raw["weekday"] = day.day.strftime("%a")
    raw["session"] = day.session_type
    raw["km"] = format_km_range(day.km_min, day.km_max)
    raw["pace"] = format_pace_range(day.pace_min, day.pace_max)
    return raw


def _plan_dict(plan: Plan) -> dict:
    recipe = asdict(plan.recipe)
    recipe["km"] = format_km_range(plan.recipe.km_min, plan.recipe.km_max)
    recipe["pace"] = format_pace_range(plan.recipe.pace_min, plan.recipe.pace_max)
    return {
        "session_type": plan.session_type,
        "title": plan.recipe.title,
        "details": plan.recipe.details,
        "why": plan.why,
        "recovery_band": plan.recovery_band,
        "summary": plan.summary,
        "recipe": recipe,
        "yesterday": plan.yesterday,
        "week_counts": plan.week_counts,
        "phase": plan.phase,
        "upcoming": plan.upcoming,
        "goal": plan.goal,
        "prediction": _prediction_dict(plan.prediction or {}),
    }


def _load_dict(load: LoadSnapshot) -> dict:
    return {
        "ctl": round(load.ctl, 1),
        "atl": round(load.atl, 1),
        "tsb": round(load.tsb, 1),
        "weekly_km": round(load.weekly_km, 1),
        "easy_km": round(load.easy_km, 1),
        "long_km": round(load.long_km, 1),
        "weekly_load": round(load.weekly_load, 1),
        "daily_load": round(load.daily_load, 1),
    }


def _prediction_dict(raw: dict | None) -> dict:
    data = dict(raw or {})
    for key in ("p10", "p50", "p90"):
        if data.get(key):
            data[f"{key}_hms"] = format_hms(data[key])
    return data


def _tomorrow_row(today: date, upcoming: list[dict] | None, calendar: list[dict] | None):
    target = (today + timedelta(days=1)).isoformat()
    for source in (calendar or [], upcoming or []):
        for item in source:
            day = item.get("day")
            if hasattr(day, "isoformat"):
                day = day.isoformat()
            if str(day)[:10] == target:
                return item
    return None
