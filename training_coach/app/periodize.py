"""Original remaining-day calendar aligned to a race date.

This is a skeleton only (easy / quality / long / rest / strength). Recovery
still overrides it in planner.overlay_calendar. Tune the ladders and PEAK_LONG_KM
if you want different workout shapes or a bigger/smaller peak long run.

Weekday indices: 0=Mon … 6=Sun.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from classify import (
    EASY_RUN,
    INTERVALS,
    LONG_RUN,
    QUALITY,
    REST,
    STRENGTH,
    TEMPO,
    Session,
)
from goal import (
    RACE_10K,
    RACE_5K,
    RACE_HALF,
    RACE_MARATHON,
    Prefs,
    end_of_plan,
    phase_for,
)
from load import LoadSnapshot
from paces import PaceSet

# Interval progressions as (reps, meters). Index 0 is the first session; a
# completed "great/ok" quality day steps one rung (never two). Taper drops one.
# Add/reorder rungs to change the menu for that race distance.
INTERVAL_LADDERS: dict[str, list[tuple[int, int]]] = {
    RACE_5K: [(6, 400), (8, 400), (10, 400), (6, 800), (8, 800)],
    RACE_10K: [(5, 800), (6, 800), (8, 800), (5, 1000), (6, 1200)],
    RACE_HALF: [(4, 1000), (5, 1000), (6, 1000), (4, 1600), (5, 1600)],
    RACE_MARATHON: [(4, 1000), (5, 1200), (4, 1600), (3, 2000)],
    "none": [(6, 400), (8, 400), (6, 800)],
}

# Tempo progressions as minutes at threshold / MP (plus ~15 min warmup + 10 cooldown).
TEMPO_LADDERS: dict[str, list[int]] = {
    RACE_5K: [15, 18, 20],
    RACE_10K: [20, 22, 25],
    RACE_HALF: [20, 25, 30],
    RACE_MARATHON: [25, 30, 40],
    "none": [20, 25, 30],
}

# Soft cap for the longest *training* long run (km). Race day uses race distance.
# Lower these if peak longs feel too big vs current fitness; the weekly +12% cap
# in _long_center still prevents a sudden jump from today's long_km.
PEAK_LONG_KM = {
    RACE_5K: 10.0,
    RACE_10K: 14.0,
    RACE_HALF: 18.0,
    RACE_MARATHON: 32.0,
    "none": 14.0,
}

# Long-run growth per remaining week (1.12 = +12%). Raise toward 1.15–1.20 for
# a more aggressive ramp; keep ≤ 1.10 if coming back from injury.
LONG_WEEKLY_GROWTH = 1.12
# Taper long is this fraction of min(current, peak). 0.55 ≈ cut volume in half.
TAPER_LONG_FRACTION = 0.55
# Warmup + cooldown kilometres added on top of interval work, or easy padding
# around a tempo (tempo uses 4.0 + minutes/5.5 instead).
QUALITY_WARMUP_KM = 3.5
# Half-width of the prescribed km range as a fraction of the centre.
# Wider = more room for recovery to pick the low end. Easy is widest.
KM_SPREAD_QUALITY = 0.12
KM_SPREAD_LONG = 0.08
KM_SPREAD_EASY = 0.18


@dataclass
class PlanDay:
    day: date
    session_type: str
    km_min: float
    km_max: float
    pace_min: float | None
    pace_max: float | None
    structure: str
    phase: str
    source: str = "skeleton"

    def as_dict(self) -> dict:
        return {
            "day": self.day,
            "session_type": self.session_type,
            "km_min": self.km_min,
            "km_max": self.km_max,
            "pace_min": self.pace_min,
            "pace_max": self.pace_max,
            "structure": self.structure,
            "phase": self.phase,
            "source": self.source,
        }


def week_template(prefs: Prefs) -> list[str]:
    """Place rest / long / quality / strength on Mon=0 … Sun=6.

    Preference lists are tried in order. Change e.g. long_pref to [6, 5, 4]
    to prefer Sunday longs over Saturday. Counts come from live HA helpers,
    not add-on config.
    """
    types = [EASY_RUN] * 7
    rest_pref = [6, 4, 0, 2]  # Sun, Fri, Mon, Wed
    placed_rest = 0
    for wd in rest_pref:
        if placed_rest >= prefs.weekly_rest_days:
            break
        types[wd] = REST
        placed_rest += 1

    long_pref = [5, 6, 4]  # Sat, Sun, Fri
    placed_long = 0
    for wd in long_pref:
        if placed_long >= prefs.weekly_long_runs:
            break
        if types[wd] == REST and prefs.weekly_rest_days:
            continue
        types[wd] = LONG_RUN
        placed_long += 1
    if placed_long < prefs.weekly_long_runs:
        for wd in range(7):
            if placed_long >= prefs.weekly_long_runs:
                break
            if types[wd] == EASY_RUN:
                types[wd] = LONG_RUN
                placed_long += 1

    quality_pref = [1, 3, 2]  # Tue, Thu, Wed — not adjacent to a typical long
    placed_q = 0
    for wd in quality_pref:
        if placed_q >= prefs.weekly_quality_runs:
            break
        if types[wd] in {LONG_RUN, REST}:
            continue
        types[wd] = INTERVALS
        placed_q += 1
    if placed_q < prefs.weekly_quality_runs:
        for wd in range(7):
            if placed_q >= prefs.weekly_quality_runs:
                break
            if types[wd] == EASY_RUN:
                types[wd] = INTERVALS
                placed_q += 1

    strength_pref = [0, 2, 4, 3]  # Mon, Wed, Fri, Thu — fill rest-or-easy slots
    placed_s = 0
    for wd in strength_pref:
        if placed_s >= prefs.weekly_strength:
            break
        if types[wd] in {LONG_RUN, INTERVALS}:
            continue
        if types[wd] == REST and prefs.weekly_rest_days <= placed_s:
            continue
        if types[wd] == REST:
            types[wd] = STRENGTH
            placed_s += 1
            continue
        types[wd] = STRENGTH
        placed_s += 1
    if placed_s < prefs.weekly_strength:
        for wd in range(7):
            if placed_s >= prefs.weekly_strength:
                break
            if types[wd] in {EASY_RUN, REST}:
                types[wd] = STRENGTH
                placed_s += 1
    return types


def _last_quality(sessions: list[Session]) -> Session | None:
    for session in sorted(sessions, key=lambda s: s.when or date.min, reverse=True):
        if session.session_type in QUALITY and session.when:
            return session
    return None


def _match_rung(session: Session, ladder: list[tuple[int, int]]) -> int:
    """Guess which ladder step the last quality session was.

    Tempo ladders store minutes as (minutes, 0). Interval ladders use
    (reps, meters); ~3.5 km is subtracted as warmup/cooldown if no splits.
    """
    if not ladder:
        return 0
    if ladder[0][1] == 0:
        work_min = max(10.0, (session.duration_min or 40.0) - 25.0)
        best = 0
        for i, (minutes, _) in enumerate(ladder):
            if abs(minutes - work_min) <= abs(ladder[best][0] - work_min):
                best = i
        return best
    work_m = 0.0
    if session.splits:
        paces = [float(s.get("pace_min_km") or 0) for s in session.splits if s.get("pace_min_km")]
        if paces:
            cutoff = sorted(paces)[len(paces) // 2]
            hard = [
                float(s.get("distance_m") or 0)
                for s, pace in zip(session.splits, paces)
                if pace <= cutoff
            ]
            work_m = sum(hard)
    if work_m <= 0 and session.distance_m:
        work_m = max(0.0, session.distance_m - QUALITY_WARMUP_KM * 1000.0)
    best = 0
    for i, (reps, meters) in enumerate(ladder):
        target = reps * meters
        if abs(target - work_m) <= abs(ladder[best][0] * ladder[best][1] - work_m):
            best = i
    return best


def _ladder_index(
    sessions: list[Session],
    prefs: Prefs,
    kind: str,
    feeling: str | None,
    last_compliance: str | None = None,
) -> int:
    """Pick the next rung. Skip/tired → hold or drop one; great/ok → step one."""
    key = prefs.race_distance if prefs.race_distance in INTERVAL_LADDERS else "none"
    if kind == INTERVALS:
        ladder = INTERVAL_LADDERS[key]
    else:
        ladder = [(n, 0) for n in TEMPO_LADDERS[key]]
    last = _last_quality(sessions)
    idx = 0
    if last and last.session_type == kind:
        idx = _match_rung(last, ladder)
        tired = feeling in {"tired", "wiped", "sore"}
        skipped = last_compliance in {"skipped", "substituted", "modified"}
        if skipped or tired:
            idx = max(0, idx - 1) if tired or last_compliance == "skipped" else idx
        elif feeling in {None, "unset", "great", "ok"}:
            idx = min(len(ladder) - 1, idx + 1)
    elif feeling in {"tired", "wiped", "sore"}:
        idx = 0
    return max(0, min(len(ladder) - 1, idx))


def _quality_for_week(week_index: int, last_quality_type: str | None) -> str:
    if last_quality_type == INTERVALS:
        return TEMPO if week_index % 2 == 0 else INTERVALS
    if last_quality_type == TEMPO:
        return INTERVALS if week_index % 2 == 0 else TEMPO
    return INTERVALS if week_index % 2 == 0 else TEMPO


def _km_range(center: float, spread: float = KM_SPREAD_EASY) -> tuple[float, float]:
    center = max(3.0, center)
    lo = max(3.0, round(center * (1 - spread), 1))
    hi = round(center * (1 + spread), 1)
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _long_center(week_index: int, n_weeks: int, load: LoadSnapshot, prefs: Prefs, phase: str) -> float:
    """Target long-run km for this week, never a sudden jump from current fitness.

    peak is min(PEAK_LONG_KM, ~85–90% of race distance). Each week may grow at
    most LONG_WEEKLY_GROWTH from today's typical long. Taper cuts volume.
    """
    current = max(8.0, load.long_km)
    peak = PEAK_LONG_KM.get(prefs.race_distance, 14.0)
    if prefs.race_km:
        peak = min(peak, max(current, prefs.race_km * (0.85 if prefs.race_distance == RACE_MARATHON else 0.9)))
    if phase == "taper":
        return max(6.0, min(current, peak) * TAPER_LONG_FRACTION)
    if phase == "race" and prefs.race_km:
        return prefs.race_km
    frac = 0.0 if n_weeks <= 1 else min(1.0, week_index / max(n_weeks - 2, 1))
    target = current + (peak - current) * frac
    cap = current * (LONG_WEEKLY_GROWTH ** max(week_index, 0))
    return min(target, cap, peak)


def _easy_center(load: LoadSnapshot, phase: str) -> float:
    """Weekday easy km from recent easy-run history, clipped 5–12 km."""
    base = max(5.0, min(load.easy_km or 7.0, 12.0))
    if phase == "taper":
        return max(4.0, base * 0.7)
    if phase == "peak":
        return base * 0.95
    return base


def interval_structure(
    prefs: Prefs,
    sessions: list[Session],
    feeling: str | None,
    phase: str,
    last_compliance: str | None = None,
) -> tuple[str, float]:
    key = prefs.race_distance if prefs.race_distance in INTERVAL_LADDERS else "none"
    ladder = INTERVAL_LADDERS[key]
    idx = _ladder_index(sessions, prefs, INTERVALS, feeling, last_compliance)
    if phase == "taper":
        idx = max(0, idx - 1)
    reps, meters = ladder[idx]
    total_km = (reps * meters) / 1000.0 + QUALITY_WARMUP_KM
    return f"{reps}×{meters} m, jog recoveries", total_km


def tempo_structure(
    prefs: Prefs,
    sessions: list[Session],
    feeling: str | None,
    phase: str,
    last_compliance: str | None = None,
) -> tuple[str, float]:
    key = prefs.race_distance if prefs.race_distance in TEMPO_LADDERS else "none"
    ladder = TEMPO_LADDERS[key]
    idx = _ladder_index(sessions, prefs, TEMPO, feeling, last_compliance)
    if phase == "taper":
        idx = max(0, idx - 1)
    minutes = ladder[min(idx, len(ladder) - 1)]
    if prefs.race_distance == RACE_MARATHON:
        label = f"{minutes} min marathon-pace / threshold"
    else:
        label = f"{minutes} min threshold"
    total_km = 4.0 + minutes / 5.5  # ~warmup/cooldown + tempo at ~5:30/km
    return f"15 min easy + {label} + 10 min easy", total_km


def build_skeleton(
    today: date,
    prefs: Prefs,
    load: LoadSnapshot,
    paces: PaceSet,
    sessions: list[Session],
    feeling: str | None = None,
    last_compliance: str | None = None,
) -> list[PlanDay]:
    end = end_of_plan(today, prefs)
    template = week_template(prefs)
    last_q = _last_quality(sessions)
    last_q_type = last_q.session_type if last_q else None
    n_weeks = max(1, (end - today).days // 7 + 1)
    days: list[PlanDay] = []
    quality_seen = 0
    week0 = today - timedelta(days=today.weekday())
    for offset in range((end - today).days + 1):
        day = today + timedelta(days=offset)
        phase = phase_for(day, prefs)
        week_index = max(0, (day - week0).days // 7)
        raw = template[day.weekday()]
        if day == prefs.race_date and prefs.has_race:
            raw = LONG_RUN
            phase = "race"
        if raw == INTERVALS:
            kind = _quality_for_week(week_index + quality_seen, last_q_type)
            quality_seen += 1
            if kind == TEMPO:
                structure, center = tempo_structure(
                    prefs, sessions, feeling, phase, last_compliance
                )
                pace_min, pace_max = paces.tempo_min, paces.tempo_max
                session_type = TEMPO
            else:
                structure, center = interval_structure(
                    prefs, sessions, feeling, phase, last_compliance
                )
                pace_min, pace_max = paces.interval_min, paces.interval_max
                session_type = INTERVALS
            if phase == "taper":
                center *= 0.75  # shorter quality block in taper; no new hard types
            km_min, km_max = _km_range(center, KM_SPREAD_QUALITY)
        elif raw == LONG_RUN:
            session_type = LONG_RUN
            center = _long_center(week_index, n_weeks, load, prefs, phase)
            km_min, km_max = _km_range(center, KM_SPREAD_LONG)
            pace_min, pace_max = paces.easy_min, paces.easy_max
            structure = "Easy long run"
            if phase == "race" and prefs.race_km:
                km_min = km_max = round(prefs.race_km, 1)
                if paces.race_pace:
                    pace_min = paces.race_pace - 5 / 60.0
                    pace_max = paces.race_pace + 10 / 60.0
                structure = "Race day"
            elif phase == "peak" and prefs.race_distance == RACE_MARATHON and paces.race_pace:
                structure = "Easy long, last 3–5 km at race pace"
        elif raw == STRENGTH:
            session_type = STRENGTH
            km_min = km_max = 0.0
            pace_min = pace_max = None
            structure = "Gym / strength"
        elif raw == REST:
            session_type = REST
            km_min = km_max = 0.0
            pace_min = pace_max = None
            structure = "Rest"
        else:
            session_type = EASY_RUN
            center = _easy_center(load, phase)
            km_min, km_max = _km_range(center, KM_SPREAD_EASY)
            pace_min, pace_max = paces.easy_min, paces.easy_max
            structure = "Easy conversational / zone 2"
        days.append(
            PlanDay(
                day=day,
                session_type=session_type,
                km_min=km_min,
                km_max=km_max,
                pace_min=pace_min,
                pace_max=pace_max,
                structure=structure,
                phase=phase,
            )
        )
    return days
