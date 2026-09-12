"""Session recipes: km + pace ranges and quality structure."""

from __future__ import annotations

from dataclasses import dataclass

from classify import EASY_RUN, INTERVALS, LONG_RUN, REST, STRENGTH, TEMPO, CROSS_HARD, CROSS_LONG, Session
from paces import PaceSet, format_pace_range
from periodize import PlanDay


@dataclass(frozen=True)
class Recipe:
    session_type: str
    title: str
    details: str
    duration_min: int
    km_min: float | None = None
    km_max: float | None = None
    pace_min: float | None = None
    pace_max: float | None = None
    structure: str = ""


def _median(values: list[float], default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def typical_durations(sessions: list[Session]) -> tuple[int, int]:
    easy = [s.duration_min for s in sessions if s.session_type == EASY_RUN and s.duration_min]
    longs = [s.duration_min for s in sessions if s.session_type == LONG_RUN and s.duration_min]
    easy_min = int(round(_median(easy, 40)))
    easy_min = max(30, min(easy_min, 55))
    if longs:
        last_long = max(longs)
        long_min = int(round(min(max(last_long * 1.1, easy_min + 20), last_long * 1.3, 120)))
    else:
        long_min = min(max(easy_min + 25, 80), 110)
    return easy_min, long_min


def _duration_from_km(km: float | None, pace: float | None, fallback: int) -> int:
    if km and pace and km > 0 and pace > 0:
        return int(round(km * pace))
    return fallback


def format_km_range(lo: float | None, hi: float | None) -> str:
    if not lo and not hi:
        return ""
    if lo is None:
        return f"{hi:g} km"
    if hi is None or abs(hi - lo) < 0.15:
        return f"{lo:g} km"
    return f"{lo:g}–{hi:g} km"


def recipe_from_plan_day(
    plan_day: PlanDay,
    sessions: list[Session],
    yesterday_type: str | None,
    *,
    low_end: bool = False,
) -> Recipe:
    km_min, km_max = plan_day.km_min, plan_day.km_max
    if low_end and km_max and km_min:
        km_max = km_min
    return build_recipe(
        plan_day.session_type,
        sessions,
        yesterday_type,
        km_min=km_min,
        km_max=km_max,
        pace_min=plan_day.pace_min,
        pace_max=plan_day.pace_max,
        structure=plan_day.structure,
    )


def build_recipe(
    session_type: str,
    sessions: list[Session],
    yesterday_type: str | None,
    *,
    km_min: float | None = None,
    km_max: float | None = None,
    pace_min: float | None = None,
    pace_max: float | None = None,
    structure: str = "",
    paces: PaceSet | None = None,
) -> Recipe:
    easy_min, long_min = typical_durations(sessions)
    if paces is not None and km_min is None and km_max is None and session_type in {
        EASY_RUN,
        LONG_RUN,
        INTERVALS,
        TEMPO,
    }:
        mid_pace = (paces.easy_min + paces.easy_max) / 2.0
        if session_type == EASY_RUN:
            center = easy_min / max(mid_pace, 4.0)
        elif session_type == LONG_RUN:
            center = long_min / max(mid_pace, 4.0)
        elif session_type == INTERVALS:
            center = 9.0
        else:
            center = 10.0
        km_min = max(3.0, round(center * 0.85, 1))
        km_max = round(center * 1.15, 1)
    if paces is not None:
        pace_min = pace_min if pace_min is not None else (
            paces.easy_min if session_type in {EASY_RUN, LONG_RUN} else
            paces.interval_min if session_type == INTERVALS else
            paces.tempo_min if session_type == TEMPO else None
        )
        pace_max = pace_max if pace_max is not None else (
            paces.easy_max if session_type in {EASY_RUN, LONG_RUN} else
            paces.interval_max if session_type == INTERVALS else
            paces.tempo_max if session_type == TEMPO else None
        )
    km_label = format_km_range(km_min, km_max)
    pace_label = format_pace_range(pace_min, pace_max)
    mid_km = None
    if km_min is not None and km_max is not None:
        mid_km = (km_min + km_max) / 2.0
    elif km_min is not None:
        mid_km = km_min
    mid_pace = None
    if pace_min is not None and pace_max is not None:
        mid_pace = (pace_min + pace_max) / 2.0

    if session_type == REST:
        return Recipe(
            REST,
            "Rest day",
            "No structured training. Optional easy walk or mobility. Sleep and food matter more today.",
            0,
        )
    if session_type == EASY_RUN:
        duration = _duration_from_km(mid_km, mid_pace, easy_min)
        title = f"Easy run {km_label}".strip() if km_label else f"Easy run ({easy_min} min)"
        if pace_label:
            title = f"{title} @ {pace_label} /km"
        details = structure or "Easy conversational pace / zone 2. Keep heart rate comfortable; finish able to talk."
        if km_label and pace_label:
            details = f"{km_label} @ {pace_label} /km. {details}"
        return Recipe(EASY_RUN, title, details, duration, km_min, km_max, pace_min, pace_max, structure)
    if session_type == LONG_RUN:
        duration = _duration_from_km(mid_km, mid_pace, long_min)
        title = f"Long run {km_label}".strip() if km_label else f"Long run ({long_min} min)"
        if structure == "Race day":
            title = f"Race day {km_label}".strip() if km_label else "Race day"
        if pace_label:
            title = f"{title} @ {pace_label} /km"
        details = structure or "Easy long run. Same easy effort as a recovery run, just more time on feet."
        if km_label and pace_label:
            details = f"{km_label} @ {pace_label} /km. {details}"
        return Recipe(LONG_RUN, title, details, duration, km_min, km_max, pace_min, pace_max, structure)
    if session_type == INTERVALS:
        reps = 6 if easy_min < 45 else 8
        fallback = 20 + reps * 5
        duration = _duration_from_km(mid_km, mid_pace, fallback)
        block = structure or f"{reps} x 400–800 m, jog recoveries"
        title = "Intervals"
        if km_label:
            title = f"Intervals {km_label}"
        if pace_label:
            title = f"{title} @ {pace_label} /km"
        title = f"{title} ({block.split(',')[0]})"
        details = f"{km_label + ' @ ' + pace_label + ' /km. ' if km_label and pace_label else ''}15 min easy warmup, {block}, 10 min easy cooldown."
        return Recipe(INTERVALS, title, details, duration, km_min, km_max, pace_min, pace_max, structure)
    if session_type == TEMPO:
        tempo_block = 20 if easy_min < 40 else 30
        fallback = 15 + tempo_block + 10
        duration = _duration_from_km(mid_km, mid_pace, fallback)
        block = structure or f"{tempo_block} min comfortably hard"
        title = "Tempo run"
        if km_label:
            title = f"Tempo {km_label}"
        if pace_label:
            title = f"{title} @ {pace_label} /km"
        details = f"{km_label + ' @ ' + pace_label + ' /km. ' if km_label and pace_label else ''}{block}."
        return Recipe(TEMPO, title, details, duration, km_min, km_max, pace_min, pace_max, structure)
    note = "Full-body strength, 45–60 min: squats or hinges, push, pull, core. Leave 1–2 reps in reserve."
    if yesterday_type in {INTERVALS, TEMPO, LONG_RUN, CROSS_HARD, CROSS_LONG}:
        note = "Strength with an upper-body bias and easy legs: push, pull, core, maybe light hinges. Skip heavy squats/lunges."
    return Recipe(STRENGTH, "Gym / strength (45–60 min)", note, 50)
