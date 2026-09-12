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
CROSS_EASY = "cross_easy"
CROSS_HARD = "cross_hard"
CROSS_LONG = "cross_long"
OTHER = "other"

SESSION_TYPES = (
    REST,
    EASY_RUN,
    LONG_RUN,
    INTERVALS,
    TEMPO,
    STRENGTH,
    CROSS_EASY,
    CROSS_HARD,
    CROSS_LONG,
)
QUALITY = {INTERVALS, TEMPO}
CROSS_TYPES = {CROSS_EASY, CROSS_HARD, CROSS_LONG}
HARD_OR_LONG = {INTERVALS, TEMPO, LONG_RUN, CROSS_HARD, CROSS_LONG}
RUN_TYPES = {EASY_RUN, LONG_RUN, INTERVALS, TEMPO}

RUN_SPORTS = {"run", "trailrun", "virtualrun"}
STRENGTH_SPORTS = {"weighttraining", "workout", "crossfit", "gym"}
BIKE_SPORTS = {
    "ride",
    "virtualride",
    "gravelride",
    "mountainbikeride",
    "ebikeride",
    "ebike",
    "cycling",
    "handcycle",
}
SKI_SPORTS = {
    "nordicski",
    "rollerski",
    "backcountryski",
    "crosscountryski",
    "xcski",
}
ALPINE_SPORTS = {"alpineski", "snowboard", "snowshoe"}
CROSS_SPORTS = BIKE_SPORTS | SKI_SPORTS | {
    "swim",
    "rowing",
    "kayaking",
    "canoeing",
    "elliptical",
    "standuppaddling",
    "ice skate",
    "iceskate",
}

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
CROSS_HARD_KEYWORDS = (
    "interval",
    "intervals",
    "vo2",
    "ftp",
    "sweet spot",
    "sweetspot",
    "threshold",
    "tempo",
    "race",
    "zwift race",
    "attack",
    "sprint",
    "over-under",
    "overunders",
    "ski-o",
    "skio",
    "time trial",
)
CROSS_EASY_KEYWORDS = (
    "easy",
    "recovery",
    "commute",
    "zone 2",
    "z2",
    "endurance",
    "technique",
)
CROSS_LONG_KEYWORDS = ("long", "fondo", "adventure", "tour")
SKI_TITLE_HINTS = (
    "skate ski",
    "skate skiing",
    "classic ski",
    "nordic",
    "rollerski",
    "roller ski",
    "xc ski",
    "cross country ski",
    "cross-country",
    "hiihto",
)


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
    activity_id: str | None = None
    splits: list | None = None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _sport_key(sport: str) -> str:
    return _norm(sport).replace(" ", "").replace("-", "").replace("_", "")


def is_bike_sport(sport: str, title: str = "") -> bool:
    key = _sport_key(sport)
    if key in BIKE_SPORTS or "ride" in key or "bike" in key or "cycl" in key:
        return True
    blob = _norm(title)
    return any(word in blob for word in ("zwift", "commute", "group ride"))


def is_ski_sport(sport: str, title: str = "") -> bool:
    key = _sport_key(sport)
    if key in ALPINE_SPORTS:
        return False
    if key in SKI_SPORTS or "nordic" in key or "rollerski" in key:
        return True
    if "ski" in key:
        return True
    return _contains_any(_norm(title), SKI_TITLE_HINTS)


def cross_long_minutes(sport: str, title: str, long_run_min_minutes: int) -> int:
    """Minutes after which a bike/ski counts as long (recovery like a long run).

    Ski uses ~1.1× the run long threshold (more like running). Bike uses ~1.4×
    (less eccentric). Raise the multipliers if 90 min skis should stay "easy".
    """
    if is_ski_sport(sport, title):
        return max(80, int(long_run_min_minutes * 1.1))
    return max(100, int(long_run_min_minutes * 1.4))


def cross_label(session_type: str, sport: str = "", title: str = "") -> str:
    kind = {CROSS_EASY: "Easy", CROSS_HARD: "Hard", CROSS_LONG: "Long"}.get(session_type)
    if not kind:
        return session_type.replace("_", " ")
    if is_ski_sport(sport, title):
        return f"{kind} ski"
    if is_bike_sport(sport, title):
        return f"{kind} ride"
    return f"{kind} cross-training"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(word in text for word in keywords)


def classify_run(
    title: str,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    long_run_min_minutes: int,
    splits_hint: str | None = None,
) -> str:
    """Title keywords win, then splits, then duration, then HR.

    long_run_min_minutes is the add-on option (default 75). Raise it if 70 min
    easy runs are being tagged as longs. HR uses avg/max of *this* activity
    (0.88 ≈ intervals, 0.82 ≈ tempo); lower the ratios if tempo is missed.
    """
    blob = _norm(title)
    if _contains_any(blob, INTERVAL_KEYWORDS):
        return INTERVALS
    if _contains_any(blob, TEMPO_KEYWORDS):
        return TEMPO
    if splits_hint in {INTERVALS, TEMPO}:
        return splits_hint
    if _contains_any(blob, LONG_KEYWORDS):
        return LONG_RUN
    if _contains_any(blob, EASY_KEYWORDS):
        return EASY_RUN
    if splits_hint:
        return splits_hint
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


def classify_cross(
    sport: str,
    title: str,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    long_run_min_minutes: int,
) -> str:
    """Easy / hard / long for bike, nordic ski, and other aerobic cross-training."""
    blob = _norm(title)
    sport_n = _sport_key(sport)
    long_min = cross_long_minutes(sport, title, long_run_min_minutes)
    if _contains_any(blob, CROSS_HARD_KEYWORDS):
        return CROSS_HARD
    if _contains_any(blob, CROSS_LONG_KEYWORDS):
        return CROSS_LONG
    if _contains_any(blob, CROSS_EASY_KEYWORDS):
        if duration_min is not None and duration_min >= long_min:
            return CROSS_LONG
        return CROSS_EASY
    peak = max_hr or 185.0
    if avg_hr and peak:
        # Cycling HR is often a bit lower than running at the same RPE.
        # 0.84 ≈ clearly hard; 0.78 ≈ tempo-ish. Raise to require higher HR
        # before a ride/ski is tagged hard.
        ratio = avg_hr / peak
        if duration_min is not None and duration_min >= long_min:
            return CROSS_HARD if ratio >= 0.84 else CROSS_LONG
        if duration_min is not None and duration_min < 80 and ratio >= 0.84:
            return CROSS_HARD
        if duration_min is not None and duration_min >= 25 and ratio >= 0.78:
            return CROSS_HARD
    if duration_min is not None and duration_min >= long_min:
        return CROSS_LONG
    if sport_n in {"ebikeride", "ebike"}:
        return CROSS_EASY
    if duration_min is not None and duration_min < 12:
        return OTHER
    return CROSS_EASY


def classify_sport(
    sport: str,
    title: str,
    duration_min: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    long_run_min_minutes: int,
) -> str:
    sport_n = _sport_key(sport)
    title_n = _norm(title)
    if sport_n in STRENGTH_SPORTS or "weight" in sport_n or "gym" in title_n:
        return STRENGTH
    is_run = sport_n in RUN_SPORTS or (not sport_n and _looks_like_run(title))
    if is_run:
        return classify_run(title, duration_min, avg_hr, max_hr, long_run_min_minutes)
    if sport_n in ALPINE_SPORTS or sport_n in {"walk", "hike", "hiking", "yoga", "pilates"}:
        return OTHER
    if (
        sport_n in CROSS_SPORTS
        or is_bike_sport(sport, title)
        or is_ski_sport(sport, title)
        or (duration_min is not None and duration_min >= 25 and (avg_hr or max_hr))
    ):
        return classify_cross(sport, title, duration_min, avg_hr, max_hr, long_run_min_minutes)
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
    activity_id = attrs.get("activity_id")
    if activity_id is not None:
        activity_id = str(activity_id)
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
        activity_id=activity_id,
    )
