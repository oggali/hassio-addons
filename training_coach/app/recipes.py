"""Session recipes: what to actually do today."""

from __future__ import annotations

from dataclasses import dataclass

from classify import EASY_RUN, INTERVALS, LONG_RUN, REST, STRENGTH, TEMPO, Session


@dataclass(frozen=True)
class Recipe:
    session_type: str
    title: str
    details: str
    duration_min: int


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


def build_recipe(
    session_type: str,
    sessions: list[Session],
    yesterday_type: str | None,
) -> Recipe:
    easy_min, long_min = typical_durations(sessions)
    if session_type == REST:
        return Recipe(
            REST,
            "Rest day",
            "No structured training. Optional easy walk or mobility. Sleep and food matter more today.",
            0,
        )
    if session_type == EASY_RUN:
        return Recipe(
            EASY_RUN,
            f"Easy run ({easy_min} min)",
            f"Easy conversational pace / zone 2 for {easy_min} minutes. Keep heart rate comfortable; finish able to talk.",
            easy_min,
        )
    if session_type == LONG_RUN:
        return Recipe(
            LONG_RUN,
            f"Long run ({long_min} min)",
            f"Easy long run about {long_min} minutes. Same easy effort as a recovery run, just more time on feet. Walk breaks are fine.",
            long_min,
        )
    if session_type == INTERVALS:
        reps = 6 if easy_min < 45 else 8
        total = 20 + reps * 5
        return Recipe(
            INTERVALS,
            f"Intervals ({reps} x 2–3 min)",
            f"15 min easy warmup, {reps} x 2–3 min hard with equal jog recoveries, 10 min easy cooldown. Hard = controlled, not a sprint.",
            total,
        )
    if session_type == TEMPO:
        tempo_block = 20 if easy_min < 40 else 30
        total = 15 + tempo_block + 10
        return Recipe(
            TEMPO,
            f"Tempo run ({tempo_block} min)",
            f"15 min easy warmup, {tempo_block} min comfortably hard (threshold / “brisk but steady”), 10 min easy cooldown.",
            total,
        )
    note = "Full-body strength, 45–60 min: squats or hinges, push, pull, core. Leave 1–2 reps in reserve."
    if yesterday_type in {INTERVALS, TEMPO, LONG_RUN}:
        note = "Strength with an upper-body bias and easy legs: push, pull, core, maybe light hinges. Skip heavy squats/lunges."
    return Recipe(STRENGTH, "Gym / strength (45–60 min)", note, 50)
