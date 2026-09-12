"""Training load: CTL / ATL / TSB and weekly volume.

Banister-style exponentially weighted averages of session load:

- CTL (chronic training load, "fitness"): slow average. Higher = more work in the bank.
- ATL (acute training load, "fatigue"): fast average. Higher = recently hammered.
- TSB (training stress balance, "form") = CTL − ATL.
  Positive TSB = relatively fresh; large negative = overreached.

Session load = duration_min × intensity. Tune INTENSITY / CTL_TAU / ATL_TAU below;
do not change add-on options for this — it is code-side on purpose.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from classify import (
    CROSS_EASY,
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
    CROSS_LONG: 0.65,  # long ride; less eccentric than a long run
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

# When a session has distance but no duration, assume this easy pace (min/km).
FALLBACK_PACE_MIN_KM = 6.0

# Typical run distances used when history has no easy/long runs yet (km).
TYPICAL_EASY_KM = 7.0
TYPICAL_LONG_KM = 12.0


@dataclass(frozen=True)
class LoadSnapshot:
    ctl: float  # fitness; published on sensor.training_coach_goal
    atl: float  # fatigue
    tsb: float  # form (ctl - atl); plan-search penalizes TSB < -25
    weekly_km: float  # running km only, last 7 days
    easy_km: float  # median easy-run distance; sizes weekday easy slots
    long_km: float  # median long-run distance; caps the long-run ramp
    weekly_load: float  # sum of session_load over last 7 days


def session_load(session: Session) -> float:
    duration = session.duration_min or 0.0
    if duration <= 0 and session.distance_m:
        duration = (session.distance_m / 1000.0) * FALLBACK_PACE_MIN_KM
    intensity = INTENSITY.get(session.session_type, 0.5)
    if session.session_type in CROSS_TYPES and is_ski_sport(session.sport, session.title or ""):
        intensity = min(SKI_LOAD_CAP, intensity + SKI_LOAD_BONUS)
    return duration * intensity


def loads_by_day(sessions: list[Session]) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for session in sessions:
        if not session.when:
            continue
        out[session.when] += session_load(session)
    return dict(out)


def ctl_atl_tsb(sessions: list[Session], today: date) -> tuple[float, float, float]:
    """Walk day-by-day from the first session through today.

    Each day: ctl += (load - ctl) / CTL_TAU  (same for ATL).
    Days with no session still decay fitness/fatigue toward 0.
    """
    daily = loads_by_day(sessions)
    if not daily:
        return 0.0, 0.0, 0.0
    start = min(daily)
    ctl = 0.0
    atl = 0.0
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
    return sum(
        session_load(s) for s in sessions if s.when and start <= s.when <= today
    )


def build_load_snapshot(sessions: list[Session], today: date) -> LoadSnapshot:
    ctl, atl, tsb = ctl_atl_tsb(sessions, today)
    return LoadSnapshot(
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        weekly_km=weekly_km(sessions, today),
        easy_km=typical_run_km(sessions, EASY_RUN, TYPICAL_EASY_KM),
        long_km=typical_run_km(sessions, LONG_RUN, TYPICAL_LONG_KM),
        weekly_load=weekly_load(sessions, today),
    )
