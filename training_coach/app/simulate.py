"""Monte Carlo finish-time bands and remaining-plan search.

Two cheap stdlib-random layers (~500–1500 draws, no numpy):

1. finish_distribution — sample a road finish around P50 (Riegel). Publishes
   P10/P50/P90 and P(hit target). Raise REL_VAR if bands feel too tight.
2. search_calendar — mutate the remaining days and pick the lowest score
   (overreach minus hit-probability). If the target is faster than P10, skip
   search and just cap long-run volume (_safe_volume).
"""

from __future__ import annotations

import random
from classify import HARD_OR_LONG, LONG_RUN, QUALITY
from goal import Prefs
from load import LoadSnapshot, long_run_floor_km
from paces import PaceSet, riegel
from periodize import LONG_WEEKLY_GROWTH, PlanDay

MC_FINISH = 500  # draws for P10/P50/P90; 200 is noisier, 2000 is slower for no gain
MC_PLAN_CANDIDATES = 10  # calendar mutations to try
MC_PLAN_SIMS = 80  # skip/overreach sims per candidate
REL_VAR = 0.11  # ~11% relative SD of a road finish; 0.09 tighter, 0.14 wider
# Day mixture around P50: most days "normal", some slow, a few outliers.
PROB_NORMAL = 0.70
PROB_OFF = 0.25  # remainder (~5%) is the outlier bucket in _day_factor
# Target is "feasible" if it is not faster than P10 (with a 2% fudge).
FEASIBLE_VS_P10 = 0.98
# Default skip chance when feedback_history has <2 samples of that session type.
DEFAULT_SKIP_P = 0.12
# TSB below this (more negative = more fatigued) adds an overreach penalty.
TSB_OVERREACH = -25.0


def _day_factor(rng: random.Random) -> float:
    u = rng.random()
    if u < PROB_NORMAL:
        return rng.gauss(0.0, 0.4 * REL_VAR)
    if u < PROB_NORMAL + PROB_OFF:
        return abs(rng.gauss(0.0, 0.6 * REL_VAR))
    if rng.random() < 0.3:
        return -abs(rng.gauss(0.0, 0.8 * REL_VAR))
    return min(abs(rng.gauss(0.0, REL_VAR * 1.2)), 0.25)


def finish_distribution(
    paces: PaceSet,
    prefs: Prefs,
    *,
    seed: int = 1,
    sims: int = MC_FINISH,
) -> dict:
    rng = random.Random(seed)
    target_km = prefs.race_km
    p50 = paces.predicted_s
    if p50 is None and paces.ref_time_s and paces.ref_distance_km and target_km:
        p50 = riegel(paces.ref_time_s, paces.ref_distance_km, target_km, paces.k)
    if p50 is None:
        return {
            "p10": None,
            "p50": None,
            "p90": None,
            "p_hit": None,
            "feasible": True,
        }
    samples = [p50 * (1.0 + _day_factor(rng)) for _ in range(sims)]
    samples.sort()

    def pct(p: float) -> float:
        idx = min(len(samples) - 1, max(0, int(round((p / 100.0) * (len(samples) - 1)))))
        return samples[idx]

    p10 = pct(10)
    p90 = pct(90)
    hit = None
    feasible = True
    if prefs.target_seconds:
        hit = sum(1 for s in samples if s <= prefs.target_seconds) / len(samples)
        feasible = prefs.target_seconds >= p10 * FEASIBLE_VS_P10
    return {
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "p_hit": hit,
        "feasible": feasible,
        "samples": sims,
    }


def _skip_rates(feedback: list[dict]) -> dict[str, float]:
    counts: dict[str, list[int]] = {}
    for row in feedback:
        planned = row.get("planned_type") or ""
        if not planned:
            continue
        bucket = counts.setdefault(planned, [0, 0])
        bucket[1] += 1
        if row.get("compliance") == "skipped":
            bucket[0] += 1
    return {k: v[0] / v[1] for k, v in counts.items() if v[1] >= 2}


def _feeling_hard_penalty(feedback: list[dict]) -> float:
    relevant = [
        r
        for r in feedback
        if r.get("recovery_band") == "good"
        and r.get("feeling") in {"tired", "wiped", "sore"}
        and r.get("planned_type") in HARD_OR_LONG
    ]
    if len(relevant) >= 2:
        return 0.25
    if relevant:
        return 0.1
    return 0.0


def _mutate(days: list[PlanDay], rng: random.Random) -> list[PlanDay]:
    out = [
        PlanDay(
            day=d.day,
            session_type=d.session_type,
            km_min=d.km_min,
            km_max=d.km_max,
            pace_min=d.pace_min,
            pace_max=d.pace_max,
            structure=d.structure,
            phase=d.phase,
            source="search",
        )
        for d in days
    ]
    if len(out) < 3:
        return out
    action = rng.choice(["drop_quality", "shrink_long", "swap_rest", "noop"])
    if action == "drop_quality":
        candidates = [i for i, d in enumerate(out) if d.session_type in QUALITY and d.phase != "race"]
        if candidates:
            i = rng.choice(candidates)
            d = out[i]
            out[i] = PlanDay(
                d.day, "easy_run", max(4.0, d.km_min * 0.7), max(5.0, d.km_max * 0.7),
                d.pace_min, d.pace_max, "Easy (quality dropped)", d.phase, "search",
            )
    elif action == "shrink_long":
        candidates = [i for i, d in enumerate(out) if d.session_type == LONG_RUN and d.phase not in {"race"}]
        if candidates:
            i = rng.choice(candidates)
            d = out[i]
            out[i] = PlanDay(
                d.day, d.session_type, d.km_min * 0.9, d.km_max * 0.9,
                d.pace_min, d.pace_max, d.structure, d.phase, "search",
            )
    elif action == "swap_rest":
        easy_idx = [i for i, d in enumerate(out) if d.session_type == "easy_run"]
        rest_idx = [i for i, d in enumerate(out) if d.session_type == "rest"]
        if easy_idx and rest_idx:
            i, j = rng.choice(easy_idx), rng.choice(rest_idx)
            out[i], out[j] = (
                PlanDay(out[i].day, "rest", 0, 0, None, None, "Rest", out[i].phase, "search"),
                PlanDay(
                    out[j].day, "easy_run", out[i].km_min, out[i].km_max,
                    out[i].pace_min, out[i].pace_max, "Easy", out[j].phase, "search",
                ),
            )
    return out


def _no_time_weekdays(feedback: list[dict]) -> set[int]:
    days: set[int] = set()
    for row in feedback:
        if row.get("skip_reason") != "no_time":
            continue
        day = row.get("day")
        weekday = getattr(day, "weekday", None)
        if callable(weekday):
            days.add(day.weekday())
    return days


def _sore_recent(feedback: list[dict]) -> bool:
    relevant = [
        r
        for r in feedback
        if r.get("skip_reason") == "sore"
        or (r.get("feeling") == "sore" and r.get("planned_type") in HARD_OR_LONG)
    ]
    return len(relevant) >= 1


def _safe_volume(
    days: list[PlanDay],
    load: LoadSnapshot,
    paces: PaceSet | None = None,
) -> list[PlanDay]:
    pace = (paces.easy_min + paces.easy_max) / 2.0 if paces else None
    floor = long_run_floor_km(load.easy_km, pace)
    cap = max(floor, max(load.long_km, 8.0) * LONG_WEEKLY_GROWTH)
    out: list[PlanDay] = []
    for day in days:
        if day.phase == "race":
            out.append(day)
            continue
        km_min, km_max = day.km_min, day.km_max
        if day.session_type == LONG_RUN and day.km_max > cap:
            km_max = round(cap, 1)
            km_min = round(min(day.km_min, km_max * 0.92), 1)
        out.append(
            PlanDay(
                day.day,
                day.session_type,
                km_min,
                km_max,
                day.pace_min,
                day.pace_max,
                day.structure,
                day.phase,
                "search",
            )
        )
    return out


def _score_plan(
    days: list[PlanDay],
    load: LoadSnapshot,
    prefs: Prefs,
    paces: PaceSet,
    skip_rates: dict[str, float],
    feeling_penalty: float,
    rng: random.Random,
    finish: dict,
    no_time_weekdays: set[int] | None = None,
    extra_spacing: bool = False,
) -> float:
    overreach = 0.0
    prev_hard = False
    gap_since_hard = 99
    weekly: dict[int, float] = {}
    blocked = no_time_weekdays or set()
    for i, day in enumerate(days):
        week = i // 7
        km = (day.km_min + day.km_max) / 2.0
        weekly[week] = weekly.get(week, 0.0) + km
        skip_p = skip_rates.get(day.session_type, DEFAULT_SKIP_P)
        if rng.random() < skip_p:
            km = 0.0
        if day.session_type == LONG_RUN and day.day.weekday() in blocked and day.day.weekday() < 5:
            overreach += 0.6
        if day.session_type in HARD_OR_LONG:
            if prev_hard:
                overreach += 1.0
            if extra_spacing and gap_since_hard < 2:
                overreach += 0.8
            if rng.random() < 0.15 + feeling_penalty:
                overreach += 0.4
            prev_hard = True
            gap_since_hard = 0
        else:
            prev_hard = False
            gap_since_hard += 1
    weeks = sorted(weekly)
    for a, b in zip(weeks, weeks[1:]):
        if weekly[a] > 1 and weekly[b] > weekly[a] * 1.15:
            overreach += 1.2
    if load.tsb < TSB_OVERREACH:
        overreach += 0.8
    time_score = 0.0
    if finish.get("p50"):
        time_score = finish["p50"] / 60.0
        if finish.get("p_hit") is not None:
            time_score -= 400.0 * finish["p_hit"]
        if not finish.get("feasible", True):
            time_score += 200.0
    return time_score + 80.0 * overreach


def search_calendar(
    days: list[PlanDay],
    load: LoadSnapshot,
    prefs: Prefs,
    paces: PaceSet,
    feedback: list[dict],
    finish: dict,
    *,
    seed: int = 7,
) -> list[PlanDay]:
    if not days:
        return days
    rng = random.Random(seed)
    skip_rates = _skip_rates(feedback)
    feeling_penalty = _feeling_hard_penalty(feedback)
    no_time_days = _no_time_weekdays(feedback)
    extra_spacing = _sore_recent(feedback)
    if not finish.get("feasible", True):
        return _safe_volume(days, load, paces)
    best = days
    best_score = _score_plan(
        days,
        load,
        prefs,
        paces,
        skip_rates,
        feeling_penalty,
        rng,
        finish,
        no_time_days,
        extra_spacing,
    )
    for i in range(MC_PLAN_CANDIDATES):
        cand = _mutate(days, random.Random(seed + 10 + i))
        score = 0.0
        local = random.Random(seed + 100 + i)
        for _ in range(MC_PLAN_SIMS):
            score += _score_plan(
                cand,
                load,
                prefs,
                paces,
                skip_rates,
                feeling_penalty,
                local,
                finish,
                no_time_days,
                extra_spacing,
            )
        score /= MC_PLAN_SIMS
        if score < best_score:
            best_score = score
            best = cand
    return best
