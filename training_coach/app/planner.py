"""Pick today's session from recovery + last week's load."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from classify import (
    EASY_RUN,
    HARD_OR_LONG,
    INTERVALS,
    LONG_RUN,
    QUALITY,
    REST,
    STRENGTH,
    TEMPO,
    Session,
)
from features import FeatureSnapshot, sessions_since, yesterday_session
from recipes import Recipe, build_recipe
from settings import Settings


TITLES = {
    REST: "Rest day",
    EASY_RUN: "Easy run",
    LONG_RUN: "Long run",
    INTERVALS: "Intervals",
    TEMPO: "Tempo run",
    STRENGTH: "Gym / strength",
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

    @property
    def summary(self) -> str:
        return f"{self.recipe.title}\n{self.recipe.details}\n\nWhy: {self.why}"


def summarize_week(snapshot: FeatureSnapshot) -> WeekCounts:
    start = snapshot.today - timedelta(days=6)
    week = sessions_since(snapshot, start)
    counts = WeekCounts()
    days: set[date] = set()
    last_hard_at: date | None = None
    for session in sorted(week, key=lambda s: s.when or date.min):
        if not session.when:
            continue
        days.add(session.when)
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
            last_hard_at = session.when
    counts.training_days = len(days)
    if last_hard_at:
        delta = datetime_hours_since(snapshot, last_hard_at)
        counts.hours_since_hard = delta
    return counts


def datetime_hours_since(snapshot: FeatureSnapshot, when: date) -> float:
    start = snapshot.now.replace(hour=12, minute=0, second=0, microsecond=0)
    # Assume the hard session happened around midday on that date.
    from datetime import datetime

    session_dt = datetime(when.year, when.month, when.day, 12, 0, tzinfo=snapshot.now.tzinfo)
    return max(0.0, (snapshot.now - session_dt).total_seconds() / 3600.0)


def next_quality(last_quality_type: str | None) -> str:
    if last_quality_type == INTERVALS:
        return TEMPO
    return INTERVALS


def pick_session_type(snapshot: FeatureSnapshot, settings: Settings) -> tuple[str, str]:
    recovery = snapshot.recovery
    week = summarize_week(snapshot)
    yesterday = yesterday_session(snapshot)
    yesterday_type = yesterday.session_type if yesterday else None
    weekday = snapshot.today.weekday()  # Mon=0 Sun=6
    weekend = weekday >= 5

    def why_recovery() -> str:
        return "; ".join(recovery.reasons[:3])

    if snapshot.already_trained_today:
        return REST, "You already have a session logged today, so extra training is not needed."

    if recovery.rest_mode:
        return REST, f"Rest mode is on ({why_recovery()})."

    if yesterday_type in HARD_OR_LONG and recovery.band == "poor":
        return REST, f"Yesterday was a {TITLES[yesterday_type].lower()} and recovery is poor ({why_recovery()})."

    if recovery.band == "poor":
        return REST, f"Recovery looks poor ({why_recovery()}). Take a full rest day."

    if yesterday_type in QUALITY:
        if recovery.band == "ok" or recovery.band == "good":
            if week.strength < settings.weekly_strength and yesterday_type != LONG_RUN:
                return STRENGTH, f"Yesterday was {TITLES[yesterday_type].lower()}; keep legs easy and get a gym session in ({week.strength}/{settings.weekly_strength} this week)."
            return EASY_RUN, f"Yesterday was {TITLES[yesterday_type].lower()}, so today is easy aerobic work."

    if yesterday_type == LONG_RUN:
        if recovery.band != "good":
            return REST, "Yesterday was a long run. Recover today."
        return EASY_RUN, "Yesterday was a long run, so keep today easy."

    if recovery.band == "ok":
        if yesterday_type in HARD_OR_LONG:
            return REST, f"Yesterday was taxing and readiness is only okay ({why_recovery()})."
        if week.strength < settings.weekly_strength:
            return STRENGTH, f"Readiness is okay, not great for a hard run. Strength is due ({week.strength}/{settings.weekly_strength} this week)."
        if week.training_days >= 5 and week.long + week.quality + week.easy + week.other >= 5:
            return REST, "Training load this week is already high and recovery is only okay."
        return EASY_RUN, f"Recovery is okay ({why_recovery()}). Keep it easy."

    # good recovery
    hours_since_hard = week.hours_since_hard
    long_open = week.long < settings.weekly_long_runs
    quality_open = week.quality < settings.weekly_quality_runs
    can_hard = hours_since_hard >= 48 and yesterday_type not in HARD_OR_LONG

    if long_open and weekend and can_hard:
        return LONG_RUN, "Recovery is good, no long run yet this week, and it is the weekend."

    if quality_open and can_hard:
        kind = next_quality(week.last_quality_type)
        label = TITLES[kind].lower()
        return kind, f"Recovery is good and the weekly quality slot is open, so {label}."

    if long_open and weekday == 4 and can_hard:
        return LONG_RUN, "No long run yet this week; Friday is a reasonable backup day."

    if week.strength < settings.weekly_strength:
        return STRENGTH, f"Gym is due ({week.strength}/{settings.weekly_strength} this week) and recovery can support it."

    rest_needed = settings.weekly_rest_days
    # Rough rest-day estimate: days in the last 7 without a session.
    rest_days = 7 - week.training_days
    if rest_days < rest_needed and week.training_days >= 5:
        return REST, "You have trained most days this week; take the planned rest day while recovery is still good."

    return EASY_RUN, f"Recovery is good ({why_recovery()}). An easy run fits the week."


def plan_day(snapshot: FeatureSnapshot, settings: Settings) -> Plan:
    session_type, why = pick_session_type(snapshot, settings)
    yesterday = yesterday_session(snapshot)
    yesterday_type = yesterday.session_type if yesterday else None
    recipe = build_recipe(session_type, snapshot.sessions, yesterday_type)
    week = summarize_week(snapshot)
    return Plan(
        session_type=session_type,
        recipe=recipe,
        why=why,
        recovery_band=snapshot.recovery.band,
        yesterday=yesterday_type,
        week_counts=week.as_dict(),
        oura_synced_today=snapshot.oura_synced_today,
    )
