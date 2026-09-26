"""Classify recent workouts into coach session types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from parse import (
    coerce_date,
    parse_date,
    parse_datetime,
    parse_duration_minutes,
    parse_float,
    state_value,
)

# Same outing on Garmin + Strava usually starts within a few minutes.
# Wider than that → separate sessions (e.g. morning + afternoon commute).
SAME_OUTING_START_WINDOW = timedelta(minutes=45)

REST = "rest"
EASY_RUN = "easy_run"
LONG_RUN = "long_run"
INTERVALS = "intervals"
TEMPO = "tempo"
STRENGTH = "strength"
CROSS_EASY = "cross_easy"
CROSS_HARD = "cross_hard"
CROSS_LONG = "cross_long"
# Long easy bike/ski: counts toward load, does NOT block next day like a long run.
CROSS_EASY_LONG = "cross_easy_long"
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
    CROSS_EASY_LONG,
)
QUALITY = {INTERVALS, TEMPO}
CROSS_TYPES = {CROSS_EASY, CROSS_HARD, CROSS_LONG, CROSS_EASY_LONG}
# cross_easy_long intentionally omitted — long Z2 bike/ski is fatigue, not a long-run gate.
# cross_long stays for legacy history rows only (new classify paths emit cross_easy_long).
HARD_OR_LONG = {INTERVALS, TEMPO, LONG_RUN, CROSS_HARD, CROSS_LONG}
RUN_TYPES = {EASY_RUN, LONG_RUN, INTERVALS, TEMPO}
TRAINING_TYPES = RUN_TYPES | CROSS_TYPES | {STRENGTH}
# Accidental GPS / stray auto-detects below this are not "already trained".
MIN_TRAINING_MINUTES = 10.0
MIN_TRAINING_METRES = 1000.0

RUN_SPORTS = {"run", "running", "trailrun", "virtualrun"}
STRENGTH_SPORTS = {
    "weighttraining",
    "weightlifting",
    "strengthtraining",
    "strength_training",
    "fitnessequipment",
    "workout",
    "crossfit",
    "gym",
}
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


def is_training_session(session: Session) -> bool:
    """True for a structured run / gym / bike / ski, not a rest-day walk."""
    if session.session_type not in TRAINING_TYPES:
        return False
    duration = session.duration_min
    distance_m = session.distance_m
    if duration is None and distance_m is None:
        return True
    if duration is not None and duration >= MIN_TRAINING_MINUTES:
        return True
    if distance_m is not None and distance_m >= MIN_TRAINING_METRES:
        return True
    return False


def session_day(session: Session) -> date | None:
    if session.started_at is not None:
        return coerce_date(session.started_at)
    return coerce_date(session.when)


def _has_clock_time(value: datetime | None) -> bool:
    """True when started_at carries a real time of day (not date-only midnight)."""
    if value is None:
        return False
    return not (value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0)


def strava_distance_metres(value: float | None) -> float | None:
    """Strava HA distance sensors are usually km; Garmin is metres."""
    if value is None:
        return None
    if value <= 0:
        return value
    # Already looks like metres (track/road distances).
    if value >= 1000:
        return value
    return value * 1000.0


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
    # Wall-clock start when the sensor provides it (used to collapse Garmin/Strava
    # of the same outing without merging morning + afternoon doubles).
    started_at: datetime | None = None
    # Strava Relative Effort (API suffer_score); only when HR was present.
    relative_effort: float | None = None
    # duration_min × intensity; filled on DuckDB upsert (see load.session_load).
    session_load: float | None = None
    # Banister walk immediately before/after this session (see load.annotate_session_banister).
    ctl_before: float | None = None
    atl_before: float | None = None
    ctl_after: float | None = None
    atl_after: float | None = None
    tsb_after: float | None = None


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
    kind = {
        CROSS_EASY: "Easy",
        CROSS_HARD: "Hard",
        CROSS_LONG: "Long",
        CROSS_EASY_LONG: "Long easy",
    }.get(session_type)
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
    """Easy / hard / long for bike, nordic ski, and other aerobic cross-training.

    Long easy (cross_easy_long) raises CTL/ATL but does not use the long-run /
    hard spacing gates. New classifications use cross_easy_long for long easy
    work; cross_long remains only for legacy DuckDB rows (still in HARD_OR_LONG).
    """
    blob = _norm(title)
    sport_n = _sport_key(sport)
    long_min = cross_long_minutes(sport, title, long_run_min_minutes)
    if _contains_any(blob, CROSS_HARD_KEYWORDS):
        return CROSS_HARD
    if _contains_any(blob, CROSS_LONG_KEYWORDS):
        return CROSS_EASY_LONG
    if _contains_any(blob, CROSS_EASY_KEYWORDS):
        if duration_min is not None and duration_min >= long_min:
            return CROSS_EASY_LONG
        return CROSS_EASY
    peak = max_hr or 185.0
    if avg_hr and peak:
        # Cycling HR is often a bit lower than running at the same RPE.
        # Short rides need a higher ratio (max spikes inflate avg/max).
        # 0.84 ≈ clearly hard for mid/long; 0.86 ≈ hard for short.
        ratio = avg_hr / peak
        if duration_min is not None and duration_min >= long_min:
            return CROSS_HARD if ratio >= 0.84 else CROSS_EASY_LONG
        if duration_min is not None and duration_min > 40 and ratio >= 0.84:
            return CROSS_HARD
        if duration_min is not None and duration_min >= 25 and ratio >= 0.86:
            return CROSS_HARD
    if duration_min is not None and duration_min >= long_min:
        return CROSS_EASY_LONG
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
    if sport_n in ALPINE_SPORTS or sport_n in {
        "walk",
        "walking",
        "hike",
        "hiking",
        "yoga",
        "pilates",
    }:
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
    raw_when = state_value(date_entity) or attrs.get("date") or attrs.get("start_date")
    started_at = parse_datetime(raw_when, tz)
    when = started_at.date() if started_at else parse_date(raw_when, tz)
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
        distance_m=strava_distance_metres(parse_float(state_value(distance_entity))),
        avg_hr=parse_float(state_value(avg_hr_entity)),
        max_hr=parse_float(state_value(max_hr_entity)),
        source="strava",
        activity_id=activity_id,
        started_at=started_at,
    )


def _garmin_sport(item: dict[str, Any]) -> str:
    raw = item.get("activityType") or item.get("activity_type") or item.get("type") or ""
    if isinstance(raw, dict):
        return str(raw.get("typeKey") or raw.get("type_key") or raw.get("type") or "")
    return str(raw)


def _garmin_duration_minutes(value: Any) -> float | None:
    """Garmin activity duration is always seconds."""
    number = parse_float(value)
    if number is None:
        return None
    return number / 60.0


def session_from_garmin_activity(
    item: dict[str, Any] | None,
    tz,
    long_run_min_minutes: int,
) -> Session | None:
    if not item:
        return None
    title = str(
        item.get("activityName") or item.get("activity_name") or item.get("name") or ""
    ).strip()
    sport = _garmin_sport(item)
    if not title and not sport:
        return None
    if not title or title.lower() in {"unknown", "unavailable"}:
        title = sport or "Garmin activity"
    activity_id = item.get("activityId") or item.get("activity_id")
    if activity_id is not None:
        activity_id = f"g:{activity_id}"
    raw_when = (
        item.get("startTimeLocal")
        or item.get("startTimeGMT")
        or item.get("startTime")
        or item.get("start_time")
        or item.get("beginTimestamp")
    )
    started_at = parse_datetime(raw_when, tz)
    when = started_at.date() if started_at else parse_date(raw_when, tz)
    duration = _garmin_duration_minutes(
        item.get("duration") or item.get("elapsedDuration") or item.get("movingDuration")
    )
    session_type = classify_sport(
        sport,
        title,
        duration,
        parse_float(item.get("averageHR") or item.get("averageHeartRate") or item.get("avgHR")),
        parse_float(item.get("maxHR") or item.get("maxHeartRate")),
        long_run_min_minutes,
    )
    return Session(
        session_type=session_type,
        title=title,
        sport=sport or "Unknown",
        when=when,
        duration_min=duration,
        distance_m=parse_float(item.get("distance") or item.get("distanceMeters")),
        avg_hr=parse_float(item.get("averageHR") or item.get("averageHeartRate") or item.get("avgHR")),
        max_hr=parse_float(item.get("maxHR") or item.get("maxHeartRate")),
        source="garmin",
        activity_id=activity_id,
        started_at=started_at,
    )


def session_from_garmin_entity(
    entity: dict[str, Any] | None,
    tz,
    long_run_min_minutes: int,
) -> Session | None:
    if not entity:
        return None
    attrs = dict(entity.get("attributes") or {})
    title = str(state_value(entity) or "").strip()
    if title and title.lower() not in {"unknown", "unavailable"}:
        attrs.setdefault("activityName", title)
    return session_from_garmin_activity(attrs, tz, long_run_min_minutes)


def session_family(session: Session) -> str:
    if session.session_type in RUN_TYPES or _sport_key(session.sport) in RUN_SPORTS:
        return "run"
    if session.session_type == STRENGTH or _sport_key(session.sport) in STRENGTH_SPORTS:
        return "strength"
    if is_ski_sport(session.sport, session.title):
        return "ski"
    if is_bike_sport(session.sport, session.title) or session.session_type in CROSS_TYPES:
        return "cross"
    return session.session_type or "other"


def effective_distance_m(session: Session) -> float | None:
    """Metres for compare/merge; fixes legacy Strava-km rows still in DuckDB."""
    if session.distance_m is None:
        return None
    if session.source == "strava" and 0 < session.distance_m < 1000:
        return session.distance_m * 1000.0
    return session.distance_m


def sessions_look_same(left: Session, right: Session) -> bool:
    """True when Garmin and Strava (or history) describe the same outing.

    Prefer start-time proximity (~45 min) so morning + afternoon doubles stay
    distinct. Without clock times, require tight duration (≤5 min) and distance.
    """
    if left.activity_id and right.activity_id and left.activity_id == right.activity_id:
        return True
    if session_day(left) != session_day(right) or session_day(left) is None:
        return False
    if session_family(left) != session_family(right):
        return False

    duration_close = (
        left.duration_min is not None
        and right.duration_min is not None
        and abs(left.duration_min - right.duration_min) <= 20
    )
    left_m = effective_distance_m(left)
    right_m = effective_distance_m(right)
    distance_close = False
    if left_m and right_m:
        longer = max(left_m, right_m)
        if longer > 0:
            distance_close = abs(left_m - right_m) / longer <= 0.25

    left_clock = _has_clock_time(left.started_at)
    right_clock = _has_clock_time(right.started_at)
    if left_clock and right_clock:
        assert left.started_at is not None and right.started_at is not None
        if abs(left.started_at - right.started_at) > SAME_OUTING_START_WINDOW:
            return False
        # Same start window: duration agreement is enough (distance units can differ).
        return duration_close or (left.duration_min is None and right.duration_min is None)

    # Date-only / legacy rows: keep morning+afternoon doubles (often ~5–10 min apart
    # in duration) while still collapsing near-identical Garmin/Strava copies.
    duration_tight = (
        left.duration_min is not None
        and right.duration_min is not None
        and abs(left.duration_min - right.duration_min) <= 5
    )
    return duration_tight and distance_close


def merge_training_sessions(*groups: list[Session]) -> list[Session]:
    """Keep Strava over Garmin over history stubs when they are the same session."""
    rank = {"strava": 0, "garmin": 1, "history": 2}

    def sort_key(session: Session) -> tuple:
        day = session_day(session) or date.min
        start_ts = session.started_at.timestamp() if session.started_at is not None else 0.0
        return (rank.get(session.source, 9), day, start_ts)

    combined: list[Session] = []
    for group in groups:
        combined.extend(group)
    combined.sort(key=sort_key)
    kept: list[Session] = []
    for session in combined:
        if any(sessions_look_same(session, existing) for existing in kept):
            continue
        kept.append(session)
    return kept
