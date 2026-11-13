"""Score a pace forecast on later runs, using only what was known before each cutoff.

The published band is the residual spread of those misses, shrunk toward the
historical 11% finish-time spread. The fixed 11% band is scored beside it.
"""

from __future__ import annotations

import math
import random
import statistics
from datetime import date, timedelta

from coach.classify import EASY_RUN, Session
from coach.goal import Prefs
from coach.paces import build_paces, riegel
from coach.performance import performance_points
from coach.simulate import REL_VAR, _day_factor

HORIZON_DAYS = 21
STEP_DAYS = 14
MIN_PAST = 4
# Residual observations that pull the published spread back to REL_VAR.
SPREAD_PRIOR = 8.0


def _band_factors(rel_var: float, *, seed: int = 1, sims: int = 400) -> tuple[float, float]:
    rng = random.Random(seed)
    factors = sorted(_day_factor(rng, rel_var) for _ in range(sims))

    def pct(p: float) -> float:
        idx = min(len(factors) - 1, max(0, int(round((p / 100.0) * (len(factors) - 1)))))
        return factors[idx]

    return pct(10), pct(90)


def _ewma(points: list, half_life: float = 14.0) -> float:
    level = points[0].pace_at_hr
    prev = points[0].day
    for point in points[1:]:
        gap = max(1, (point.day - prev).days)
        alpha = 1 - math.exp(-math.log(2) * gap / half_life)
        level = level + alpha * (point.pace_at_hr - level)
        prev = point.day
    return level


def _riegel_pace(paces, point) -> float | None:
    """Predicted min/km for this effort from the past reference, via Riegel."""
    if paces.ref_time_s and paces.ref_distance_km and point.distance_km > 0:
        seconds = riegel(paces.ref_time_s, paces.ref_distance_km, point.distance_km, paces.k)
        return (seconds / 60.0) / point.distance_km
    if point.pace_min_km:
        return point.pace_min_km
    return None


def _mae(errors: list[float]) -> float | None:
    if not errors:
        return None
    return sum(abs(error) for error in errors) / len(errors)


def good_morning_hard_rate(feedback: list[dict] | None) -> tuple[int, float | None]:
    """Share of good mornings whose evening came back too hard or wiped."""
    rows = []
    for row in feedback or []:
        if row.get("recovery_band") != "good":
            continue
        fit = row.get("effort_fit")
        feeling = row.get("feeling")
        if fit in (None, "", "unset") and feeling in (None, "", "unset"):
            continue
        rows.append(row)
    if not rows:
        return 0, None
    hard = sum(1 for row in rows if row.get("effort_fit") == "too_hard" or row.get("feeling") == "wiped")
    return len(rows), hard / len(rows)


def backtest_report(
    sessions: list[Session],
    feedback: list[dict] | None = None,
    prefs: Prefs | None = None,
    today: date | None = None,
    hr_max: float | None = None,
) -> dict:
    """Next 21 days of easy pace-at-HR, from past data only."""
    feedback = feedback or []
    prefs = prefs or Prefs.defaults()
    dated = [session.when for session in sessions if session.when]
    if today is None:
        today = max(dated) if dated else date.today()
    points = [
        point
        for point in performance_points(sessions, feedback, hr_max)
        if point.kept and point.session_type == EASY_RUN and point.pace_at_hr
    ]
    mornings, hard_rate = good_morning_hard_rate(feedback)
    low_11, high_11 = _band_factors(REL_VAR)
    samples: list[tuple[float, float]] = []
    last_errors: list[float] = []
    ewma_errors: list[float] = []
    cutoffs = 0
    if len(points) >= MIN_PAST + 1:
        cursor = points[0].day + timedelta(days=28)
        last_cutoff = today - timedelta(days=HORIZON_DAYS)
        while cursor <= last_cutoff:
            cutoff = cursor
            cursor += timedelta(days=STEP_DAYS)
            past = [point for point in points if point.day < cutoff]
            future = [
                point
                for point in points
                if cutoff <= point.day < cutoff + timedelta(days=HORIZON_DAYS)
            ]
            if len(past) < MIN_PAST or not future:
                continue
            past_sessions = [session for session in sessions if session.when and session.when < cutoff]
            past_feedback = [
                row for row in feedback if isinstance(row.get("day"), date) and row["day"] < cutoff
            ]
            paces = build_paces(past_sessions, prefs, cutoff, feedback=past_feedback)
            last = past[-1].pace_at_hr or past[-1].pace_min_km
            ewma = _ewma(past)
            cutoffs += 1
            for point in future:
                forecast = _riegel_pace(paces, point)
                if forecast is None or forecast <= 0:
                    continue
                actual = point.pace_at_hr or point.pace_min_km
                samples.append((forecast, actual))
                last_errors.append(actual - last)
                ewma_errors.append(actual - ewma)
    riegel_errors = [actual - forecast for forecast, actual in samples]
    residuals = [(actual / forecast - 1.0) for forecast, actual in samples if forecast > 0]
    rel_var = REL_VAR
    if len(residuals) >= 8:
        spread = statistics.pstdev(residuals)
        rel_var = (len(residuals) * spread + SPREAD_PRIOR * REL_VAR) / (len(residuals) + SPREAD_PRIOR)
    low_pub, high_pub = (low_11, high_11) if rel_var == REL_VAR else _band_factors(rel_var)

    def _cover(low_factor: float, high_factor: float) -> int:
        hits = 0
        for forecast, actual in samples:
            low = forecast * (1.0 + low_factor)
            high = forecast * (1.0 + high_factor)
            if min(low, high) <= actual <= max(low, high):
                hits += 1
        return hits

    scored = len(samples)
    coverage_11 = (_cover(low_11, high_11) / scored) if scored else None
    coverage = (_cover(low_pub, high_pub) / scored) if scored else None
    return {
        "horizon_days": HORIZON_DAYS,
        "cutoffs": cutoffs,
        "points": scored,
        "riegel_mae": _mae(riegel_errors),
        "last_mae": _mae(last_errors),
        "ewma_mae": _mae(ewma_errors),
        "baseline_coverage": coverage_11,
        "coverage": coverage,
        "rel_var": rel_var,
        "good_morning_days": mornings,
        "good_morning_hard_rate": hard_rate,
    }
