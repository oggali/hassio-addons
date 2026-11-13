"""Training load: CTL / ATL / TSB and weekly volume.

Banister-style exponentially weighted averages of session load:

- CTL (chronic training load, "fitness"): slow average. Higher = more work in the bank.
- ATL (acute training load, "fatigue"): fast average. Higher = recently hammered.
- TSB (training stress balance, "form") = CTL − ATL.
  Positive TSB = relatively fresh; large negative = overreached.

Session load is a heart-rate TRIMP or a Strava suffer score when that signal
exists, otherwise duration_min × a type intensity. CTL_TAU and ATL_TAU stay
fixed. The personal number is fatigue_gain, fitted elsewhere, which scales
ATL when the week is scored. A running impulse sits beside the systemic one:
rides and skis raise fatigue and the published CTL, and they do not enter
running_ctl. Tune the constants below — do not expose them as add-on options.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from coach.classify import (
    CROSS_EASY,
    CROSS_EASY_LONG,
    CROSS_HARD,
    CROSS_LONG,
    CROSS_TYPES,
    EASY_RUN,
    INTERVALS,
    LONG_RUN,
    RUN_TYPES,
    STRENGTH,
    TEMPO,
    Session,
    is_ski_sport,
)

# Relative cost of a minute of each session type. 1.0 ≈ all-out running.
# Raise a value to make that session type "heavier" on CTL/ATL (coach gets more
# conservative after it). Lower it if you feel the coach overreacts.
INTENSITY = {
    EASY_RUN: 0.6,  # conversational / Z2
    LONG_RUN: 0.7,  # easy but long; more cost than a short easy run
    TEMPO: 0.85,  # threshold / marathon-pace block
    INTERVALS: 0.95,  # VO2 / repeats; almost a full hard hour
    STRENGTH: 0.4,  # gym; little running-specific fatigue
    CROSS_EASY: 0.45,  # easy bike/spin; less than an easy run
    CROSS_EASY_LONG: 0.55,  # long Z2 bike/ski; more than short easy, less than hard
    CROSS_LONG: 0.65,  # legacy taxing long ride; less eccentric than a long run
    CROSS_HARD: 0.8,  # bike/ski intervals or a high-HR session
    "other": 0.5,  # unknown sport with duration
    "rest": 0.0,
}

# Extra intensity added on top of CROSS_* when the sport is nordic / skate ski
# (more legs than the same minutes on a bike). Raise if ski days still feel
# under-counted; lower toward 0 to treat ski like cycling.
SKI_LOAD_BONUS = 0.08
SKI_LOAD_CAP = 0.95  # never score ski harder than intervals

# EWMA time constants in days. Banister defaults are 42 and 7.
# Lower CTL_TAU (e.g. 30) = fitness reacts faster to the last month.
# Raise ATL_TAU (e.g. 10) = fatigue fades slower, more rest after hard weeks.
CTL_TAU = 42.0
ATL_TAU = 7.0

# Assumed resting HR for the Banister reserve when the session has no resting value.
REST_HR_ASSUMED = 60.0
# Male Banister exponent. Sex is not on the account, so this stays the one constant.
TRIMP_EXP = 1.92
# Suffer points per minute, clamped onto the same intensity scale as the type table.
SUFFER_PER_MIN_MIN = 0.2
SUFFER_PER_MIN_MAX = 1.2
# Opening CTL/ATL match the mean daily load of the first month once the history
# is at least this long, so the series does not spend six weeks climbing out of 0.
BURN_IN_DAYS = 28


def _trimp_per_min(hrr: float) -> float:
    return hrr * 0.64 * math.exp(TRIMP_EXP * hrr)


# Scale so an easy reserve (0.60) weighs the same as an easy minute (0.60).
TRIMP_TO_EASY = INTENSITY[EASY_RUN] / _trimp_per_min(0.60)

# When a session has distance but no duration, assume this easy pace (min/km).
FALLBACK_PACE_MIN_KM = 6.0

# Typical run distances used when history has no easy/long runs yet (km).
TYPICAL_EASY_KM = 7.0
TYPICAL_LONG_KM = 14.0
# A long run must be a long run, not a slightly longer easy day.
# Classifier "long" is duration ≥ 75 min, so the median tagged long sits
# just over that bar (~12–14 km at 6:00/km). Floor against weekday easy
# and ~90 min at easy pace instead.
LONG_EASY_RATIO = 2.2
MIN_LONG_MINUTES = 90
# Weekly-longest runs below this are "easy-only weeks", not longs.
WEEKLY_LONG_MIN_KM = 9.0


@dataclass(frozen=True)
class LoadSnapshot:
    ctl: float  # fitness; published on sensor.training_coach_goal
    atl: float  # fatigue
    tsb: float  # form (ctl - atl); plan-search penalizes TSB < -25
    weekly_km: float  # running km only, last 7 days
    easy_km: float  # median easy-run distance; sizes weekday easy slots
    long_km: float  # typical long (weekly longest / classified); floored vs easy in periodize
    weekly_load: float  # sum of session_load over last 7 days
    daily_load: float = 0.0  # sum of session_load on `today`
    running_ctl: float = 0.0  # running impulse only; rides do not move this
    fatigue_gain: float = 1.0  # scales ATL when a week is scored; 1 is the constant


def session_load(session: Session, hr_max: float | None = None) -> float:
    """Systemic impulse. Suffer score, else HR-TRIMP, else minutes × type intensity."""
    duration = session.duration_min or 0.0
    if duration <= 0 and session.distance_m:
        duration = (session.distance_m / 1000.0) * FALLBACK_PACE_MIN_KM
    intensity = INTENSITY.get(session.session_type, 0.5)
    if session.session_type in CROSS_TYPES and is_ski_sport(session.sport, session.title or ""):
        intensity = min(SKI_LOAD_CAP, intensity + SKI_LOAD_BONUS)
    if duration <= 0:
        return 0.0
    effort = session.relative_effort
    if effort is not None and effort > 0:
        per_min = min(SUFFER_PER_MIN_MAX, max(SUFFER_PER_MIN_MIN, effort / duration))
        return duration * per_min
    top = hr_max or session.max_hr
    avg = session.avg_hr
    if avg and top and top > REST_HR_ASSUMED and avg > REST_HR_ASSUMED:
        hrr = (avg - REST_HR_ASSUMED) / (top - REST_HR_ASSUMED)
        hrr = min(1.0, max(0.0, hrr))
        return duration * _trimp_per_min(hrr) * TRIMP_TO_EASY
    return duration * intensity


def impulse(session: Session, hr_max: float | None = None) -> float:
    """Stored systemic load when the caller did not pass a max heart rate."""
    if hr_max is None and session.session_load is not None:
        return float(session.session_load)
    return session_load(session, hr_max)


def running_impulse(session: Session, hr_max: float | None = None) -> float:
    """Running book. A ride or ski adds fatigue and published CTL, not this."""
    if session.session_type not in RUN_TYPES:
        return 0.0
    return impulse(session, hr_max)


def annotate_session_banister(sessions: list[Session], today: date | None = None) -> list[Session]:
    """Stamp each dated session with CTL/ATL before→after this session's load.

    Walks chronologically (when_day, started_at). Empty days between sessions
    still decay toward 0 (same τ as planning). Multiple sessions on one day
    each apply their own EWMA step in start-time order so you can see the
    marginal impact of every workout in the sessions table.

    Planning / load_daily still use the day-summed Banister in ctl_atl_tsb —
    end-of-day values can differ slightly on multi-session days.
    """
    dated = [s for s in sessions if s.when is not None]
    undated = [s for s in sessions if s.when is None]
    for session in undated:
        session.ctl_before = None
        session.atl_before = None
        session.ctl_after = None
        session.atl_after = None
        session.tsb_after = None

    dated.sort(
        key=lambda s: (
            s.when,
            s.started_at or datetime.min.replace(tzinfo=timezone.utc),
            s.title or "",
            s.activity_id or "",
        )
    )
    if not dated:
        return sessions

    cursor = dated[0].when
    end = today or dated[-1].when
    assert cursor is not None and end is not None
    daily = loads_by_day(dated)
    opening = _opening_level(daily, cursor, end)
    ctl = opening
    atl = opening
    for session in dated:
        day = session.when
        assert day is not None
        while cursor < day:
            ctl += (0.0 - ctl) / CTL_TAU
            atl += (0.0 - atl) / ATL_TAU
            cursor += timedelta(days=1)
        load = impulse(session)
        session.session_load = load
        session.ctl_before = ctl
        session.atl_before = atl
        ctl += (load - ctl) / CTL_TAU
        atl += (load - atl) / ATL_TAU
        session.ctl_after = ctl
        session.atl_after = atl
        session.tsb_after = ctl - atl
        cursor = day
    return sessions


def loads_by_day(sessions: list[Session], *, running: bool = False) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for session in sessions:
        if not session.when:
            continue
        load = running_impulse(session) if running else impulse(session)
        out[session.when] += load
    return dict(out)


def _opening_level(daily: dict[date, float], start: date, end: date) -> float:
    """Steady-state prior: mean daily load of the first month, including rest days."""
    if (end - start).days < BURN_IN_DAYS:
        return 0.0
    total = 0.0
    day = start
    stop = start + timedelta(days=BURN_IN_DAYS - 1)
    count = 0
    while day <= stop and day <= end:
        total += daily.get(day, 0.0)
        count += 1
        day += timedelta(days=1)
    if count == 0:
        return 0.0
    return total / count


def ewma_trace(daily: dict[date, float], end: date, tau: float) -> dict[date, float]:
    """End-of-day level from the first loaded day through `end`."""
    if not daily or tau <= 0:
        return {}
    start = min(daily)
    if end < start:
        return {}
    level = _opening_level(daily, start, end)
    out: dict[date, float] = {}
    day = start
    while day <= end:
        level += (daily.get(day, 0.0) - level) / tau
        out[day] = level
        day += timedelta(days=1)
    return out


def ctl_atl_tsb(sessions: list[Session], today: date) -> tuple[float, float, float]:
    """Walk day-by-day from the first session through today.

    Each day: ctl += (load - ctl) / CTL_TAU  (same for ATL).
    Days with no session still decay fitness/fatigue toward 0.
    A history of at least 28 days starts from the first month's mean load.
    """
    daily = loads_by_day(sessions)
    if not daily:
        return 0.0, 0.0, 0.0
    start = min(daily)
    ctl = _opening_level(daily, start, today)
    atl = ctl
    day = start
    while day <= today:
        load = daily.get(day, 0.0)
        ctl += (load - ctl) / CTL_TAU
        atl += (load - atl) / ATL_TAU
        day += timedelta(days=1)
    return ctl, atl, ctl - atl


def _median(values: list[float], default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def typical_run_km(sessions: list[Session], session_type: str, default: float) -> float:
    dists = [
        s.distance_m / 1000.0
        for s in sessions
        if s.session_type == session_type and s.distance_m and s.distance_m > 500
    ]
    return _median(dists, default)


def typical_weekly_longest_km(sessions: list[Session], default: float) -> float:
    """Median of each week's longest run. Catches weekend runs just under the long tag."""
    by_week: dict[tuple[int, int], float] = {}
    for session in sessions:
        if not session.when or session.session_type not in RUN_TYPES:
            continue
        if not session.distance_m or session.distance_m <= 500:
            continue
        iso = session.when.isocalendar()
        key = (int(iso[0]), int(iso[1]))
        km = session.distance_m / 1000.0
        by_week[key] = max(by_week.get(key, 0.0), km)
    values = [km for km in by_week.values() if km >= WEEKLY_LONG_MIN_KM]
    if not values:
        return default
    return _median(values, default)


def long_run_floor_km(easy_km: float, easy_pace: float | None = None) -> float:
    """Minimum long-run centre: 2.2× weekday easy, or 90 min at easy pace."""
    easy = max(5.0, min(easy_km or TYPICAL_EASY_KM, 12.0))
    pace = easy_pace if easy_pace and easy_pace > 4.0 else FALLBACK_PACE_MIN_KM
    return max(easy * LONG_EASY_RATIO, MIN_LONG_MINUTES / pace)


def weekly_km(sessions: list[Session], today: date, days: int = 7) -> float:
    """Running kilometres only — bike/ski distance must not inflate race volume."""
    start = today - timedelta(days=days - 1)
    metres = 0.0
    for session in sessions:
        if not session.when or session.when < start or session.when > today:
            continue
        if session.session_type in RUN_TYPES and session.distance_m:
            metres += session.distance_m
    return metres / 1000.0


def weekly_load(sessions: list[Session], today: date, days: int = 7) -> float:
    start = today - timedelta(days=days - 1)
    return sum(impulse(s) for s in sessions if s.when and start <= s.when <= today)


def build_load_snapshot(sessions: list[Session], today: date) -> LoadSnapshot:
    ctl, atl, tsb = ctl_atl_tsb(sessions, today)
    running_daily = loads_by_day(sessions, running=True)
    running_trace = ewma_trace(running_daily, today, CTL_TAU)
    running_ctl = running_trace.get(today, 0.0)
    classified_long = typical_run_km(sessions, LONG_RUN, 0.0)
    weekly_long = typical_weekly_longest_km(sessions, 0.0)
    long_km = max(classified_long, weekly_long)
    if long_km <= 0:
        long_km = TYPICAL_LONG_KM
    daily = loads_by_day(sessions).get(today, 0.0)
    return LoadSnapshot(
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        weekly_km=weekly_km(sessions, today),
        easy_km=typical_run_km(sessions, EASY_RUN, TYPICAL_EASY_KM),
        long_km=long_km,
        weekly_load=weekly_load(sessions, today),
        daily_load=daily,
        running_ctl=running_ctl,
    )
