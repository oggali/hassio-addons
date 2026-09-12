"""Pace bands from history and Riegel race equivalents.

Easy pace is the *slower* of (recent easy-run median) vs (race pace + ~45 s/km)
so an ambitious marathon goal does not prescribe 4:30 easy if you jog 6:00.

Riegel: t2 = t1 * (d2/d1)^k. Default k=1.06 (road). Fit k from ≥2 efforts at
different distances; clip to 0.8–1.3. Raise DEFAULT_RIEGEL_K if you fade more
than average on longer races; lower it if you are endurance-strong.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from classify import EASY_RUN, INTERVALS, LONG_RUN, QUALITY, RUN_TYPES, TEMPO, Session
from goal import (
    RACE_10K,
    RACE_5K,
    RACE_HALF,
    RACE_KM,
    RACE_MARATHON,
    Prefs,
    format_hms,
)

DEFAULT_RIEGEL_K = 1.06  # typical road exponent; 1.0 = even pace, 1.2 = big fade
MIN_RIEGEL_K = 0.8
MAX_RIEGEL_K = 1.3
MONTH_DAYS = 30.437
# Recency half-life for fitting k / picking a reference effort (months).
# 18 ≈ last two seasons matter; lower (e.g. 6) to ignore last year's races.
RIEGEL_HALF_LIFE_MONTHS = 18.0
# Easy band half-width (seconds/km) and how much slower than race pace easy is.
EASY_BAND_S_PER_KM = 20
EASY_VS_RACE_MIN_KM = 0.75  # 45 s/km; raise toward 1.0–1.5 if easy still feels fast
# Interval/tempo band half-width (seconds/km).
QUALITY_BAND_S_PER_KM = 10
# Only use the goal clock for training zones if it is within 8% of predicted.
TARGET_VS_PREDICTED_FLOOR = 0.92


@dataclass(frozen=True)
class PaceSet:
    easy_min: float
    easy_max: float
    interval_min: float
    interval_max: float
    tempo_min: float
    tempo_max: float
    race_pace: float | None
    k: float
    ref_distance_km: float | None
    ref_time_s: float | None
    predicted_s: float | None

    def as_dict(self) -> dict:
        return {
            "easy": [self.easy_min, self.easy_max],
            "intervals": [self.interval_min, self.interval_max],
            "tempo": [self.tempo_min, self.tempo_max],
            "race_pace": self.race_pace,
            "k": self.k,
            "ref_distance_km": self.ref_distance_km,
            "ref_time_s": self.ref_time_s,
            "predicted_s": self.predicted_s,
            "predicted": format_hms(self.predicted_s),
        }


def format_pace(min_per_km: float | None) -> str:
    if min_per_km is None or min_per_km <= 0:
        return ""
    minutes = int(min_per_km)
    seconds = int(round((min_per_km - minutes) * 60))
    if seconds >= 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def format_pace_range(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return ""
    a, b = (lo, hi) if lo <= hi else (hi, lo)
    return f"{format_pace(a)}–{format_pace(b)}"


def riegel(time_s: float, from_km: float, to_km: float, k: float = DEFAULT_RIEGEL_K) -> float:
    if from_km <= 0 or to_km <= 0 or time_s <= 0:
        return time_s
    return time_s * (to_km / from_km) ** k


def recency_weight(when: date | None, today: date, half_life_months: float = RIEGEL_HALF_LIFE_MONTHS) -> float:
    if when is None:
        return 0.3
    months = max(0.0, (today - when).days / MONTH_DAYS)
    return math.exp(-math.log(2) * months / half_life_months)


def _effort_pace(session: Session) -> tuple[float, float] | None:
    """Return (distance_km, time_s) for a usable effort."""
    if session.session_type not in RUN_TYPES:
        return None
    if not session.distance_m or session.distance_m < 1500:
        return None
    if not session.duration_min or session.duration_min < 6:
        return None
    km = session.distance_m / 1000.0
    seconds = session.duration_min * 60.0
    pace = (seconds / 60.0) / km
    if pace < 2.5 or pace > 10:
        return None
    return km, seconds


def _median(values: list[float], default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def easy_pace_min_km(sessions: list[Session], today: date) -> float:
    paces: list[float] = []
    cutoff = today - timedelta(days=180)
    for session in sessions:
        if session.session_type != EASY_RUN or not session.when or session.when < cutoff:
            continue
        effort = _effort_pace(session)
        if not effort:
            continue
        km, seconds = effort
        paces.append((seconds / 60.0) / km)
    if paces:
        return _median(paces, 6.0)
    for session in sessions:
        if session.session_type not in {EASY_RUN, LONG_RUN}:
            continue
        effort = _effort_pace(session)
        if effort:
            km, seconds = effort
            paces.append((seconds / 60.0) / km)
    return _median(paces, 6.0)


def collect_efforts(sessions: list[Session], today: date) -> list[tuple[float, float, float]]:
    """(distance_km, time_s, weight) quality-biased efforts."""
    out: list[tuple[float, float, float]] = []
    cutoff = today - timedelta(days=540)
    for session in sessions:
        if not session.when or session.when < cutoff:
            continue
        effort = _effort_pace(session)
        if not effort:
            continue
        km, seconds = effort
        weight = recency_weight(session.when, today)
        if session.session_type in QUALITY:
            weight *= 1.6
        elif session.session_type == LONG_RUN:
            weight *= 0.8
        elif session.session_type == EASY_RUN:
            weight *= 0.35
        out.append((km, seconds, weight))
    return out


def fit_riegel_k(efforts: list[tuple[float, float, float]]) -> float:
    usable = [(d, t, w) for d, t, w in efforts if d >= 3 and t > 0 and w > 0]
    if len(usable) < 2:
        return DEFAULT_RIEGEL_K
    spans = max(d for d, _, _ in usable) / max(min(d for d, _, _ in usable), 0.1)
    if spans < 1.25:
        return DEFAULT_RIEGEL_K
    sum_w = sum_wx = sum_wy = sum_wxx = sum_wxy = 0.0
    for distance, time_s, weight in usable:
        x = math.log(distance)
        y = math.log(time_s)
        sum_w += weight
        sum_wx += weight * x
        sum_wy += weight * y
        sum_wxx += weight * x * x
        sum_wxy += weight * x * y
    denom = sum_w * sum_wxx - sum_wx * sum_wx
    if abs(denom) < 1e-9 or sum_w <= 0:
        return DEFAULT_RIEGEL_K
    k = (sum_w * sum_wxy - sum_wx * sum_wy) / denom
    return max(MIN_RIEGEL_K, min(MAX_RIEGEL_K, k))


def best_reference(efforts: list[tuple[float, float, float]]) -> tuple[float, float] | None:
    if not efforts:
        return None
    scored = []
    for km, seconds, weight in efforts:
        pace = (seconds / 60.0) / km
        scored.append((pace / max(weight, 0.05), km, seconds))
    scored.sort()
    _, km, seconds = scored[0]
    return km, seconds


def build_paces(sessions: list[Session], prefs: Prefs, today: date) -> PaceSet:
    easy = easy_pace_min_km(sessions, today)
    efforts = collect_efforts(sessions, today)
    k = fit_riegel_k(efforts)
    ref = best_reference(efforts)
    if ref is None and easy:
        ref = (8.0, easy * 0.88 * 60.0 * 8.0)
    ref_km = ref[0] if ref else None
    ref_s = ref[1] if ref else None
    target_km = prefs.race_km
    predicted_s = None
    if ref_km and ref_s and target_km:
        predicted_s = riegel(ref_s, ref_km, target_km, k)
    elif ref_km and ref_s:
        predicted_s = ref_s

    zone_km, zone_s = ref_km, ref_s
    if prefs.target_seconds and target_km:
        # Insane target (faster than ~92% of predicted) does not rewrite zones.
        if predicted_s is None or prefs.target_seconds >= predicted_s * TARGET_VS_PREDICTED_FLOOR:
            zone_km, zone_s = target_km, prefs.target_seconds
    race_pace = None
    if zone_km and zone_s:
        race_pace = (zone_s / 60.0) / zone_km
    elif predicted_s and target_km:
        race_pace = (predicted_s / 60.0) / target_km

    eq5 = None
    eq10 = None
    eq_half = None
    if zone_km and zone_s:
        eq5 = riegel(zone_s, zone_km, RACE_KM[RACE_5K], k) / 60.0 / RACE_KM[RACE_5K]
        eq10 = riegel(zone_s, zone_km, RACE_KM[RACE_10K], k) / 60.0 / RACE_KM[RACE_10K]
        eq_half = riegel(zone_s, zone_km, RACE_KM[RACE_HALF], k) / 60.0 / RACE_KM[RACE_HALF]
    if eq5 is None:
        # No race/reference: scale easy pace (lower factor = faster). 0.82 ≈ 5k.
        eq5 = easy * 0.82
        eq10 = easy * 0.86
        eq_half = easy * 0.90

    goal_easy = easy
    if race_pace:
        goal_easy = max(easy, race_pace + EASY_VS_RACE_MIN_KM)
    easy_min = goal_easy - (EASY_BAND_S_PER_KM / 60.0)
    easy_max = goal_easy + (EASY_BAND_S_PER_KM / 60.0)

    interval_center = eq5
    tempo_center = eq_half if prefs.race_distance in {RACE_HALF, RACE_MARATHON} else eq10
    if prefs.race_distance == RACE_5K:
        tempo_center = eq10
    elif prefs.race_distance == RACE_10K:
        tempo_center = (eq5 + eq10) / 2
    elif prefs.race_distance == RACE_MARATHON and race_pace:
        tempo_center = (eq_half + race_pace) / 2

    pad = QUALITY_BAND_S_PER_KM / 60.0
    last_quality = next(
        (
            session
            for session in sorted(sessions, key=lambda s: s.when or date.min, reverse=True)
            if session.session_type in QUALITY
        ),
        None,
    )
    if last_quality is not None:
        effort = _effort_pace(last_quality)
        if effort:
            km, seconds = effort
            observed = (seconds / 60.0) / km
            center = interval_center if last_quality.session_type == INTERVALS else tempo_center
            if observed < center - pad:
                nudged = (center + observed) / 2.0
                floor = (eq5 if last_quality.session_type == INTERVALS else eq10) - 5 / 60.0
                if last_quality.session_type == INTERVALS:
                    interval_center = max(floor, nudged)
                else:
                    tempo_center = max(floor, nudged)

    return PaceSet(
        easy_min=max(3.5, easy_min),
        easy_max=min(9.5, easy_max),
        interval_min=max(3.0, interval_center - pad),
        interval_max=interval_center + pad,
        tempo_min=max(3.2, tempo_center - pad),
        tempo_max=tempo_center + pad,
        race_pace=race_pace,
        k=k,
        ref_distance_km=ref_km,
        ref_time_s=ref_s,
        predicted_s=predicted_s,
    )
