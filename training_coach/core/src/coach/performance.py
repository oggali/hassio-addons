"""Pace at a heart rate, and the one fatigue gain fitted to it.

The race forecast stays a Riegel projection. This module is the series that
projection is checked against, and the personal fatigue multiplier. Time
constants stay 42 and 7. One tap does not move the gain or a pace band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from coach.classify import EASY_RUN, INTERVALS, RUN_TYPES, TEMPO, Session
from coach.load import ATL_TAU, CTL_TAU, ewma_trace, loads_by_day
from coach.parse import parse_float

# Completed-session compliance. Duplicated so this module does not import feedback.
DID_SESSION = {"match", "same_family", "substituted"}
# Pace-center step. Three agreeing answers move one step; five move two.
NUDGE_MIN_NET = 3
NUDGE_STEP_MIN = 5 / 60
NUDGE_WINDOW = 6
# Easy points with this much cardiac drift are not steady aerobic pace.
DRIFT_DROP = 0.10
# Prior observations pulling the fatigue gain back to 1.
GAIN_PRIOR = 8.0
GAIN_MIN = 0.6
GAIN_MAX = 1.8
# Minutes per km slower per point of ATL, at a gain of 1.
FATIGUE_SLOPE = 0.004
# Readiness modifier. Below this correlation the series does not scale fatigue.
READY_MIN = 8
READY_CORR = 0.30
READY_CLAMP = (0.85, 1.15)
PACE_TYPES = {EASY_RUN, INTERVALS, TEMPO}


@dataclass(frozen=True)
class PerfPoint:
    day: date
    session_type: str
    pace_min_km: float
    distance_km: float
    hr: float | None
    pace_at_hr: float | None
    drift: float | None
    kept: bool


def _feedback_on(feedback: list[dict], day: date) -> dict:
    found = [row for row in feedback if row.get("day") == day]
    return found[-1] if found else {}


def _types(row: dict) -> set[str]:
    raw = str(row.get("actual_type") or "")
    parts = {part.strip() for part in raw.split(",") if part.strip()}
    planned = row.get("planned_type")
    if not parts and planned:
        parts.add(str(planned))
    return parts


def _split_rows(session: Session) -> list[tuple[float, float | None, float | None]]:
    """Kilometre splits as (distance_m, pace_min_km, heart rate), first km included."""
    rows: list[tuple[float, float | None, float | None]] = []
    for row in session.splits or []:
        if not isinstance(row, dict):
            continue
        distance = parse_float(row.get("distance_m")) or parse_float(row.get("distance")) or 0.0
        if distance < 400:
            continue
        pace = parse_float(row.get("pace_min_km"))
        if pace is None:
            moving = parse_float(row.get("moving_time_s")) or parse_float(row.get("moving_time"))
            if moving and distance:
                pace = (moving / 60.0) / (distance / 1000.0)
        if pace is not None and not 2.5 <= pace <= 12:
            pace = None
        hr = parse_float(row.get("average_heartrate")) or parse_float(row.get("avg_hr"))
        rows.append((distance, pace, hr))
    return rows


def _steady_pace(session: Session) -> float | None:
    """Pace with the first kilometre dropped when the splits say how.

    The opening kilometre is cardiac lag. The session average is the fallback.
    """
    rows = [(distance, pace) for distance, pace, _hr in _split_rows(session) if pace]
    if len(rows) >= 4:
        body = rows[1:]
        metres = sum(distance for distance, _pace in body)
        minutes = sum(pace * (distance / 1000.0) for distance, pace in body)
        if metres > 0 and minutes > 0:
            pace = minutes / (metres / 1000.0)
            if 2.5 <= pace <= 10:
                return pace
    if not session.distance_m or not session.duration_min or session.distance_m < 1500:
        return None
    if session.duration_min < 6:
        return None
    pace = session.duration_min / (session.distance_m / 1000.0)
    if pace < 2.5 or pace > 10:
        return None
    return pace


def _drift(session: Session) -> float | None:
    """Fractional rise from the first half of the run to the second, after km 1."""
    rows = _split_rows(session)
    if len(rows) < 4:
        return None
    body = rows[1:]
    if len(body) < 3:
        return None
    mid = len(body) // 2
    early, late = body[:mid], body[mid:]

    def _mean(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        return sum(values) / len(values)

    early_hr = _mean([hr for _d, _p, hr in early if hr])
    late_hr = _mean([hr for _d, _p, hr in late if hr])
    if early_hr and late_hr and early_hr > 0:
        return (late_hr - early_hr) / early_hr
    early_pace = _mean([pace for _d, pace, _h in early if pace])
    late_pace = _mean([pace for _d, pace, _h in late if pace])
    if early_pace and late_pace and early_pace > 0:
        return (late_pace - early_pace) / early_pace
    return None


def _reference_hr(sessions: list[Session], hr_max: float | None) -> float | None:
    hrs = [
        session.avg_hr
        for session in sessions
        if session.session_type == EASY_RUN and session.avg_hr and session.avg_hr > 40
    ]
    if len(hrs) >= 3:
        ordered = sorted(hrs)
        return ordered[len(ordered) // 2]
    if hr_max and hr_max > 0:
        return 0.75 * hr_max
    if hrs:
        return sum(hrs) / len(hrs)
    return None


def _blocked(row: dict) -> bool:
    return row.get("effort_fit") == "too_hard" or row.get("feeling") == "wiped"


def performance_points(
    sessions: list[Session],
    feedback: list[dict] | None = None,
    hr_max: float | None = None,
) -> list[PerfPoint]:
    """One point per run. Easy points marked too hard or wiped are not kept."""
    feedback = feedback or []
    ref = _reference_hr(sessions, hr_max)
    points: list[PerfPoint] = []
    for session in sessions:
        if session.session_type not in RUN_TYPES or session.when is None:
            continue
        pace = _steady_pace(session)
        if pace is None:
            continue
        hr = session.avg_hr if session.avg_hr and session.avg_hr > 40 else None
        pace_at = pace * (hr / ref) if hr and ref else pace
        drift = _drift(session)
        row = _feedback_on(feedback, session.when)
        kept = True
        if session.session_type == EASY_RUN and _blocked(row):
            kept = False
        if session.session_type == EASY_RUN and drift is not None and drift > DRIFT_DROP:
            kept = False
        points.append(
            PerfPoint(
                day=session.when,
                session_type=session.session_type,
                pace_min_km=pace,
                distance_km=(session.distance_m or 0.0) / 1000.0,
                hr=hr,
                pace_at_hr=pace_at,
                drift=drift,
                kept=kept,
            )
        )
    points.sort(key=lambda point: point.day)
    return points


def blocked_easy_days(feedback: list[dict] | None) -> set[date]:
    """Easy-run days whose check-in says the effort was not aerobic."""
    days: set[date] = set()
    for row in feedback or []:
        day = row.get("day")
        if not isinstance(day, date) or not _blocked(row):
            continue
        if EASY_RUN in _types(row):
            days.add(day)
    return days


def pace_nudge_min(feedback: list[dict] | None, session_type: str) -> float:
    """Minutes per km to add to a pace center. Positive is slower.

    Counts completed days whose morning band was good. About-right answers
    shrink the step back to zero. Fewer than three on one side does nothing.
    """
    if session_type not in PACE_TYPES:
        return 0.0
    rows = []
    for row in feedback or []:
        if not isinstance(row.get("day"), date):
            continue
        if row.get("recovery_band") != "good":
            continue
        if row.get("compliance") not in DID_SESSION:
            continue
        if session_type not in _types(row):
            continue
        fit = row.get("effort_fit")
        if fit not in {"too_easy", "about_right", "too_hard"}:
            continue
        rows.append(row)
    rows.sort(key=lambda row: row["day"])
    recent = rows[-NUDGE_WINDOW:]
    if len(recent) < NUDGE_MIN_NET:
        return 0.0
    hard = sum(1 for row in recent if row.get("effort_fit") == "too_hard")
    easy = sum(1 for row in recent if row.get("effort_fit") == "too_easy")
    right = sum(1 for row in recent if row.get("effort_fit") == "about_right")
    if right >= hard and right >= easy:
        return 0.0
    net = hard - easy
    if abs(net) < NUDGE_MIN_NET:
        return 0.0
    steps = 1 if abs(net) < 5 else 2
    return math.copysign(steps * NUDGE_STEP_MIN, net)


def _levels(sessions: list[Session], today: date) -> tuple[dict[date, float], dict[date, float]]:
    systemic = ewma_trace(loads_by_day(sessions), today, ATL_TAU)
    running = ewma_trace(loads_by_day(sessions, running=True), today, CTL_TAU)
    return systemic, running


def _checkin_score(row: dict) -> float | None:
    """Positive means the day cost more than a good morning expected."""
    if row.get("recovery_band") != "good":
        return None
    skipped = row.get("compliance") == "skipped" or row.get("did_plan") == "skipped"
    if skipped and row.get("skip_reason") in {"tired", "sore"}:
        return 1.0
    if row.get("compliance") not in DID_SESSION and not skipped:
        return None
    if skipped:
        return None
    score = 0.0
    marked = False
    fit = row.get("effort_fit")
    feeling = row.get("feeling")
    if fit == "too_hard" or feeling == "wiped":
        score += 1.0
        marked = True
    elif fit == "too_easy" or feeling == "great":
        score -= 0.5
        marked = True
    elif feeling == "tired":
        score += 0.5
        marked = True
    elif fit == "about_right" or feeling == "ok":
        marked = True
    if not marked:
        return None
    return score


def _regress_slope(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 4:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var < 1e-9:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / var


def _shrink(estimate: float, n: float) -> float:
    value = (n * estimate + GAIN_PRIOR * 1.0) / (n + GAIN_PRIOR)
    return min(GAIN_MAX, max(GAIN_MIN, value))


def fit_fatigue_gain(
    sessions: list[Session],
    feedback: list[dict] | None = None,
    today: date | None = None,
    hr_max: float | None = None,
) -> float:
    """One gain on ATL. Tau stays fixed. Shrinks to 1 until the history is long."""
    feedback = feedback or []
    if today is None:
        dated = [session.when for session in sessions if session.when]
        today = max(dated) if dated else date.today()
    points = [
        point
        for point in performance_points(sessions, feedback, hr_max)
        if point.kept and point.session_type == EASY_RUN and point.pace_at_hr
    ]
    atl_trace, _running = _levels(sessions, today)
    pace_gain = 1.0
    pace_n = 0.0
    if len(points) >= 4:
        atls = [atl_trace.get(point.day, 0.0) for point in points]
        paces = [point.pace_at_hr or 0.0 for point in points]
        slope = _regress_slope(atls, paces)
        if slope is not None:
            pace_gain = slope / FATIGUE_SLOPE
            pace_n = float(len(points))
    scores: list[tuple[float, float]] = []
    for row in feedback:
        day = row.get("day")
        score = _checkin_score(row)
        if not isinstance(day, date) or score is None:
            continue
        scores.append((atl_trace.get(day, 0.0), score))
    check_gain = 1.0
    check_n = 0.0
    if len(scores) >= 4:
        ordered = sorted(score[0] for score in scores)
        mid = ordered[len(ordered) // 2]
        high = [score for atl, score in scores if atl >= mid]
        low = [score for atl, score in scores if atl < mid]
        if high and low and max(atl for atl, _score in scores) > min(atl for atl, _score in scores):
            delta = (sum(high) / len(high)) - (sum(low) / len(low))
            check_gain = 1.0 + 0.5 * delta
            check_n = float(len(scores))
    if pace_n == 0 and check_n == 0:
        return 1.0
    blended = (pace_n * pace_gain + check_n * check_gain) / (pace_n + check_n)
    return _shrink(blended, pace_n + check_n)


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < READY_MIN:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx < 1e-9 or vy < 1e-9:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(vx * vy)


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def readiness_factor(
    sessions: list[Session],
    readiness: list[dict] | None,
    today: date,
    hr_max: float | None = None,
    feedback: list[dict] | None = None,
) -> float:
    """Scale fatigue when a slow readiness strain tracks the pace residual.

    Returns 1 when the series is short or the correlation is weak. This does
    not vote on today's recovery band.
    """
    rows = []
    for row in readiness or []:
        day = _as_date(row.get("day"))
        if day is None or day > today:
            continue
        rows.append({**row, "day": day})
    if len(rows) < READY_MIN:
        return 1.0
    points = [
        point
        for point in performance_points(sessions, feedback, hr_max)
        if point.kept and point.session_type == EASY_RUN and point.pace_at_hr and point.day <= today
    ]
    if len(points) < READY_MIN:
        return 1.0
    def hrv_index(row: dict) -> float | None:
        ratio = parse_float(row.get("hrv_ratio"))
        if ratio and ratio > 0:
            return ratio
        balance = parse_float(row.get("hrv_balance"))
        if balance and balance > 0:
            return balance / 80.0
        return None

    resting = [parse_float(row.get("resting_hr")) for row in rows]
    resting_vals = [value for value in resting if value]
    rest_mid = sorted(resting_vals)[len(resting_vals) // 2] if resting_vals else None
    strains: dict[date, float] = {}
    for row in rows:
        parts = []
        hrv = hrv_index(row)
        if hrv is not None:
            parts.append(1.0 - hrv)
        rest = parse_float(row.get("resting_hr"))
        if rest is not None and rest_mid:
            parts.append((rest - rest_mid) / 5.0)
        temp = parse_float(row.get("temp_dev"))
        if temp is not None:
            parts.append(temp / 0.3)
        if parts:
            strains[row["day"]] = sum(parts) / len(parts)
    if len(strains) < READY_MIN:
        return 1.0
    # Trailing week of strain, paired with that day's pace residual.
    median_pace = sorted(point.pace_at_hr or 0.0 for point in points)[len(points) // 2]
    xs: list[float] = []
    ys: list[float] = []
    holdout = today - timedelta(days=21)
    for point in points:
        if point.day > holdout:
            continue
        window = [
            strains[day]
            for day in strains
            if point.day - timedelta(days=6) <= day <= point.day
        ]
        if not window:
            continue
        xs.append(sum(window) / len(window))
        ys.append((point.pace_at_hr or 0.0) - median_pace)
    corr = _corr(xs, ys)
    if corr is None or abs(corr) < READY_CORR:
        return 1.0
    recent_days = [day for day in strains if today - timedelta(days=6) <= day <= today]
    if not recent_days:
        return 1.0
    current = sum(strains[day] for day in recent_days) / len(recent_days)
    history = list(strains.values())
    mid = sum(history) / len(history)
    var = sum((value - mid) ** 2 for value in history) / len(history)
    sd = math.sqrt(var) or 1.0
    z = (current - mid) / sd
    factor = 1.0 + 0.10 * corr * z
    return min(READY_CLAMP[1], max(READY_CLAMP[0], factor))
