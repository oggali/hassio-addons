"""Pick today's session from recovery, weekly load, and optional race calendar.

Recovery always wins over the periodized calendar. HARD_SPACING_HOURS is the
main knob for stacking quality/long; weekly caps live in HA helpers, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from classify import (
    CROSS_EASY,
    CROSS_HARD,
    CROSS_LONG,
    CROSS_TYPES,
    EASY_RUN,
    HARD_OR_LONG,
    INTERVALS,
    LONG_RUN,
    QUALITY,
    REST,
    STRENGTH,
    TEMPO,
    Session,
    cross_label,
    is_training_session,
    session_day,
)
from features import FeatureSnapshot, sessions_since, yesterday_session
from goal import Prefs
from periodize import PlanDay
from paces import PaceSet
from recipes import Recipe, build_recipe, recipe_from_plan_day
from settings import Settings

# Minimum hours after intervals/tempo/long (or hard/long cross) before another
# hard/long run. 48 = skip the next calendar day. Raise to 72 for more recovery.
HARD_SPACING_HOURS = 48


TITLES = {
    REST: "Rest day",
    EASY_RUN: "Easy run",
    LONG_RUN: "Long run",
    INTERVALS: "Intervals",
    TEMPO: "Tempo run",
    STRENGTH: "Gym / strength",
    CROSS_EASY: "Easy ride / ski",
    CROSS_HARD: "Hard ride / ski",
    CROSS_LONG: "Long ride / ski",
}


@dataclass
class WeekCounts:
    long: int = 0
    quality: int = 0
    strength: int = 0
    easy: int = 0
    other: int = 0
    rest: int = 0
    training_days: int = 0
    hours_since_hard: float = 999.0
    last_quality_type: str | None = None

    def as_dict(self) -> dict[str, int | float | str | None]:
        return {
            "long": self.long,
            "quality": self.quality,
            "strength": self.strength,
            "easy": self.easy,
            "other": self.other,
            "training_days": self.training_days,
            "hours_since_hard": round(self.hours_since_hard, 1),
            "last_quality_type": self.last_quality_type,
        }


@dataclass
class Plan:
    session_type: str
    recipe: Recipe
    why: str
    recovery_band: str
    yesterday: str | None
    week_counts: dict
    oura_synced_today: bool
    upcoming: list[dict] = field(default_factory=list)
    goal: dict | None = None
    prediction: dict | None = None
    phase: str | None = None

    @property
    def summary(self) -> str:
        return f"{self.recipe.title}\n{self.recipe.details}\n\nWhy: {self.why}"


def summarize_week(snapshot: FeatureSnapshot) -> WeekCounts:
    start = snapshot.today - timedelta(days=6)
    week = sessions_since(snapshot, start)
    counts = WeekCounts()
    days: set[date] = set()
    last_hard_at: date | None = None
    for session in sorted(week, key=lambda s: session_day(s) or date.min):
        when = session_day(session)
        if not when or not is_training_session(session):
            continue
        days.add(when)
        if session.session_type == LONG_RUN:
            counts.long += 1
        elif session.session_type in QUALITY:
            counts.quality += 1
            counts.last_quality_type = session.session_type
        elif session.session_type == STRENGTH:
            counts.strength += 1
        elif session.session_type == EASY_RUN:
            counts.easy += 1
        else:
            counts.other += 1
        if session.session_type in HARD_OR_LONG:
            last_hard_at = when
    counts.training_days = len(days)
    if last_hard_at:
        counts.hours_since_hard = datetime_hours_since(snapshot, last_hard_at)
    return counts


def datetime_hours_since(snapshot: FeatureSnapshot, when: date) -> float:
    from datetime import datetime

    session_dt = datetime(when.year, when.month, when.day, 12, 0, tzinfo=snapshot.now.tzinfo)
    return max(0.0, (snapshot.now - session_dt).total_seconds() / 3600.0)


def describe_session(session_type: str, session: Session | None = None) -> str:
    if session_type in CROSS_TYPES:
        sport = session.sport if session else ""
        title = session.title if session else ""
        return cross_label(session_type, sport, title)
    return TITLES.get(session_type, session_type.replace("_", " "))


def next_quality(last_quality_type: str | None) -> str:
    if last_quality_type == INTERVALS:
        return TEMPO
    return INTERVALS


def pick_session_type(snapshot: FeatureSnapshot, prefs: Prefs) -> tuple[str, str]:
    recovery = snapshot.recovery
    week = summarize_week(snapshot)
    yesterday = yesterday_session(snapshot)
    yesterday_type = yesterday.session_type if yesterday else None
    weekday = snapshot.today.weekday()
    weekend = weekday >= 5

    yesterday_label = describe_session(yesterday_type, yesterday) if yesterday_type else ""

    def why_recovery() -> str:
        return "; ".join(recovery.reasons[:3])

    if snapshot.already_trained_today:
        return REST, "You already have a session logged today, so extra training is not needed."

    if recovery.rest_mode:
        return REST, f"Rest mode is on ({why_recovery()})."

    if yesterday_type in HARD_OR_LONG and recovery.band == "poor":
        return REST, f"Yesterday was a {yesterday_label.lower()} and recovery is poor ({why_recovery()})."

    if recovery.band == "poor":
        return REST, f"Recovery looks poor ({why_recovery()}). Take a full rest day."

    if yesterday_type in QUALITY or yesterday_type == CROSS_HARD:
        if recovery.band in {"ok", "good"}:
            if week.strength < prefs.weekly_strength and yesterday_type != LONG_RUN:
                return STRENGTH, (
                    f"Yesterday was {yesterday_label.lower()}; keep legs easy and get a gym session in "
                    f"({week.strength}/{prefs.weekly_strength} this week)."
                )
            return EASY_RUN, f"Yesterday was {yesterday_label.lower()}, so today is easy aerobic work."

    if yesterday_type in {LONG_RUN, CROSS_LONG}:
        if recovery.band != "good":
            return REST, f"Yesterday was a {yesterday_label.lower()}. Recover today."
        return EASY_RUN, f"Yesterday was a {yesterday_label.lower()}, so keep today easy."

    if recovery.band == "ok":
        if yesterday_type in HARD_OR_LONG:
            return REST, f"Yesterday was taxing and readiness is only okay ({why_recovery()})."
        if week.strength < prefs.weekly_strength:
            return STRENGTH, (
                f"Readiness is okay, not great for a hard run. Strength is due "
                f"({week.strength}/{prefs.weekly_strength} this week)."
            )
        if week.training_days >= 5 and week.long + week.quality + week.easy + week.other >= 5:
            return REST, "Training load this week is already high and recovery is only okay."
        return EASY_RUN, f"Recovery is okay ({why_recovery()}). Keep it easy."

    hours_since_hard = week.hours_since_hard
    long_open = week.long < prefs.weekly_long_runs
    quality_open = week.quality < prefs.weekly_quality_runs
    can_hard = hours_since_hard >= HARD_SPACING_HOURS and yesterday_type not in HARD_OR_LONG

    if long_open and weekend and can_hard:
        return LONG_RUN, "Recovery is good, no long run yet this week, and it is the weekend."

    if quality_open and can_hard:
        kind = next_quality(week.last_quality_type)
        label = TITLES[kind].lower()
        return kind, f"Recovery is good and the weekly quality slot is open, so {label}."

    if long_open and weekday == 4 and can_hard:
        return LONG_RUN, "No long run yet this week; Friday is a reasonable backup day."

    if week.strength < prefs.weekly_strength:
        return STRENGTH, (
            f"Gym is due ({week.strength}/{prefs.weekly_strength} this week) and recovery can support it."
        )

    rest_needed = prefs.weekly_rest_days
    rest_days = 7 - week.training_days
    if rest_days < rest_needed and week.training_days >= 5:
        return REST, "You have trained most days this week; take the planned rest day while recovery is still good."

    return EASY_RUN, f"Recovery is good ({why_recovery()}). An easy run fits the week."


def overlay_calendar(
    snapshot: FeatureSnapshot,
    prefs: Prefs,
    intended: PlanDay,
) -> tuple[str, str, bool]:
    """Return (session_type, why, use_low_km). Recovery still wins."""
    recovery = snapshot.recovery
    yesterday = yesterday_session(snapshot)
    yesterday_type = yesterday.session_type if yesterday else None
    week = summarize_week(snapshot)

    yesterday_label = describe_session(yesterday_type, yesterday) if yesterday_type else ""

    def why_recovery() -> str:
        return "; ".join(recovery.reasons[:3])

    if snapshot.already_trained_today:
        return REST, "You already have a session logged today, so extra training is not needed.", False
    if recovery.rest_mode:
        return REST, f"Rest mode is on ({why_recovery()}).", False
    if yesterday_type in HARD_OR_LONG and recovery.band == "poor":
        return REST, (
            f"Yesterday was a {yesterday_label.lower()} and recovery is poor ({why_recovery()})."
        ), False
    if recovery.band == "poor":
        return REST, f"Recovery looks poor ({why_recovery()}). Take a full rest day.", False

    intended_type = intended.session_type
    phase_bit = f" ({intended.phase})" if intended.phase else ""

    if recovery.band == "ok":
        if intended_type in HARD_OR_LONG:
            if week.strength < prefs.weekly_strength:
                return STRENGTH, (
                    f"Calendar wanted {TITLES.get(intended_type, intended_type).lower()}{phase_bit}, "
                    f"but readiness is only okay so strength instead."
                ), True
            return EASY_RUN, (
                f"Calendar wanted {TITLES.get(intended_type, intended_type).lower()}{phase_bit}; "
                f"recovery is only okay so use the easy/low end."
            ), True
        return intended_type, (
            f"On the plan: {TITLES.get(intended_type, intended_type).lower()}{phase_bit}. "
            f"Recovery is okay, so stay on the low end of the range."
        ), True

    hours_since_hard = week.hours_since_hard
    if intended_type in HARD_OR_LONG and (
        hours_since_hard < HARD_SPACING_HOURS or yesterday_type in HARD_OR_LONG
    ):
        return EASY_RUN, (
            f"Plan had {TITLES.get(intended_type, intended_type).lower()}{phase_bit}, "
            f"but a hard/long session was too recent, so easy today."
        ), True

    return intended_type, (
        f"Recovery is good and the {intended.phase or 'week'} plan calls for "
        f"{TITLES.get(intended_type, intended_type).lower()}."
    ), False


def plan_day(
    snapshot: FeatureSnapshot,
    settings: Settings,
    prefs: Prefs | None = None,
    calendar_today: PlanDay | None = None,
    upcoming: list[dict] | None = None,
    prediction: dict | None = None,
    goal: dict | None = None,
    paces: PaceSet | None = None,
) -> Plan:
    prefs = prefs or Prefs.defaults()
    yesterday = yesterday_session(snapshot)
    yesterday_type = yesterday.session_type if yesterday else None
    low_end = False
    phase = None
    if calendar_today is not None:
        session_type, why, low_end = overlay_calendar(snapshot, prefs, calendar_today)
        phase = calendar_today.phase
        if session_type == calendar_today.session_type:
            recipe = recipe_from_plan_day(
                calendar_today, snapshot.sessions, yesterday_type, low_end=low_end
            )
        else:
            recipe = build_recipe(
                session_type,
                snapshot.sessions,
                yesterday_type,
                paces=paces,
            )
    else:
        session_type, why = pick_session_type(snapshot, prefs)
        recipe = build_recipe(session_type, snapshot.sessions, yesterday_type, paces=paces)
    if prediction and prefs.has_race and prediction.get("feasible") is False:
        why = (
            f"{why} Target is faster than the P10 band, so mileage stays honest "
            "instead of chasing an unreachable clock."
        )
    week = summarize_week(snapshot)
    return Plan(
        session_type=session_type,
        recipe=recipe,
        why=why,
        recovery_band=snapshot.recovery.band,
        yesterday=yesterday_type,
        week_counts=week.as_dict(),
        oura_synced_today=snapshot.oura_synced_today,
        upcoming=upcoming or [],
        goal=goal,
        prediction=prediction,
        phase=phase,
    )
