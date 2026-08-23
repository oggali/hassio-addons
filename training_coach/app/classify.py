"""Classify recent workouts into coach session types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from parse import parse_date, parse_duration_minutes, parse_float, state_value

REST = "rest"
EASY_RUN = "easy_run"
LONG_RUN = "long_run"
INTERVALS = "intervals"
TEMPO = "tempo"
STRENGTH = "strength"
OTHER = "other"

SESSION_TYPES = (REST, EASY_RUN, LONG_RUN, INTERVALS, TEMPO, STRENGTH)
QUALITY = {INTERVALS, TEMPO}
HARD_OR_LONG = {INTERVALS, TEMPO, LONG_RUN}
RUN_TYPES = {EASY_RUN, LONG_RUN, INTERVALS, TEMPO}

RUN_SPORTS = {"run", "trailrun", "virtualrun"}
STRENGTH_SPORTS = {"weighttraining", "workout", "crossfit", "gym"}

INTERVAL_KEYWORDS = (
    "interval",
    "intervals",
    "repeat",
    "repeats",
    "track",
    "vo2",
    "speed",
    "fartlek",
    "strides",
)
TEMPO_KEYWORDS = ("tempo", "threshold", "cruise", "lactate", "steady-state")
EASY_KEYWORDS = ("easy", "recovery", "shakeout", "jog", "zone 2", "z2")
LONG_KEYWORDS = ("long", "lsd")


@dataclass
class Session:
    session_type: str
    title: str
    sport: str
    when: date | None
    duration_min: float | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    source: str = "strava"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(word in text for word in keywords)


def classify_run(
    title: str,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    long_run_min_minutes: int,
) -> str:
    blob = _norm(title)
    if _contains_any(blob, INTERVAL_KEYWORDS):
        return INTERVALS
    if _contains_any(blob, TEMPO_KEYWORDS):
        return TEMPO
    if _contains_any(blob, LONG_KEYWORDS):
        return LONG_RUN
    if _contains_any(blob, EASY_KEYWORDS):
        return EASY_RUN
    if duration_min is not None and duration_min >= long_run_min_minutes:
        return LONG_RUN
    peak = max_hr or 190.0
    if avg_hr and peak:
        ratio = avg_hr / peak
        if duration_min is not None and duration_min < 55 and ratio >= 0.88:
            return INTERVALS
        if duration_min is not None and duration_min >= 20 and ratio >= 0.82:
            return TEMPO
    return EASY_RUN


def classify_sport(
    sport: str,
    title: str,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    long_run_min_minutes: int,
) -> str:
    sport_n = _norm(sport).replace(" ", "")
    title_n = _norm(title)
    if sport_n in STRENGTH_SPORTS or "weight" in sport_n or "gym" in title_n:
        return STRENGTH
    is_run = sport_n in RUN_SPORTS or (not sport_n and _looks_like_run(title))
    if is_run:
        return classify_run(title, duration_min, avg_hr, max_hr, long_run_min_minutes)
    return OTHER


def _looks_like_run(title: str) -> bool:
    blob = _norm(title)
    return any(word in blob for word in ("run", "easy", "tempo", "interval", "long jog", "jog"))


def session_from_strava_slot(
    activity_entity: dict[str, Any] | None,
    date_entity: dict[str, Any] | None,
    distance_entity: dict[str, Any] | None,
    moving_entity: dict[str, Any] | None,
    elapsed_entity: dict[str, Any] | None,
    avg_hr_entity: dict[str, Any] | None,
    max_hr_entity: dict[str, Any] | None,
    tz,
    long_run_min_minutes: int,
) -> Session | None:
    title = str(state_value(activity_entity) or "").strip()
    if not title or title.lower() in {"unknown", "unavailable"}:
        return None
    attrs = (activity_entity or {}).get("attributes") or {}
    sport = str(attrs.get("sport_type") or attrs.get("activity_type") or "")
    when = parse_date(state_value(date_entity) or attrs.get("date"), tz)
    duration = parse_duration_minutes(state_value(moving_entity)) or parse_duration_minutes(
        state_value(elapsed_entity)
    )
    session_type = classify_sport(
        sport,
        title,
        duration,
        parse_float(state_value(avg_hr_entity)),
        parse_float(state_value(max_hr_entity)),
        long_run_min_minutes,
    )
    return Session(
        session_type=session_type,
        title=title,
        sport=sport or "Unknown",
        when=when,
        duration_min=duration,
        distance_m=parse_float(state_value(distance_entity)),
        avg_hr=parse_float(state_value(avg_hr_entity)),
        max_hr=parse_float(state_value(max_hr_entity)),
        source="strava",
    )
