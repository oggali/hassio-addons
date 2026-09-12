"""Parse sensor.strava_latest_splits (current + history) and classify runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from classify import INTERVALS, TEMPO, Session
from parse import last_updated, parse_float

SPLIT_RUN_SPORTS = {"run", "trailrun", "virtualrun"}


@dataclass
class SplitSet:
    activity_id: str
    activity_name: str
    activity_type: str
    distance_m: float | None
    moving_time_s: float | None
    splits: list[dict[str, Any]] = field(default_factory=list)
    laps: list[dict[str, Any]] = field(default_factory=list)
    last_changed: datetime | None = None

    @property
    def when(self) -> date | None:
        return self.last_changed.date() if self.last_changed else None

    @property
    def duration_min(self) -> float | None:
        if self.moving_time_s is None:
            return None
        return self.moving_time_s / 60.0


def _aid(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def parse_split_entity(entity: dict[str, Any] | None, tz: ZoneInfo) -> SplitSet | None:
    if not entity:
        return None
    attrs = entity.get("attributes") or {}
    activity_id = _aid(attrs.get("activity_id"))
    splits = attrs.get("splits_metric") or []
    laps = attrs.get("laps") or []
    if not activity_id or (not splits and not laps):
        return None
    return SplitSet(
        activity_id=activity_id,
        activity_name=str(attrs.get("activity_name") or ""),
        activity_type=str(attrs.get("activity_type") or ""),
        distance_m=parse_float(attrs.get("distance_m")),
        moving_time_s=parse_float(attrs.get("moving_time_s")),
        splits=list(splits) if isinstance(splits, list) else [],
        laps=list(laps) if isinstance(laps, list) else [],
        last_changed=last_updated(entity, tz),
    )


def collect_split_sets(
    current: dict[str, Any] | None,
    history: list[list[dict[str, Any]]] | None,
    tz: ZoneInfo,
) -> dict[str, SplitSet]:
    """Newest snapshot per activity_id, from live state plus recorder history."""
    by_id: dict[str, SplitSet] = {}

    def consider(entity: dict[str, Any] | None) -> None:
        parsed = parse_split_entity(entity, tz)
        if not parsed:
            return
        existing = by_id.get(parsed.activity_id)
        if existing is None:
            by_id[parsed.activity_id] = parsed
            return
        old = existing.last_changed
        new = parsed.last_changed
        if new and (old is None or new > old):
            by_id[parsed.activity_id] = parsed

    consider(current)
    for series in history or []:
        for point in series:
            consider(point)
    return by_id


def _km_paces(splits: list[dict[str, Any]]) -> list[float]:
    paces: list[float] = []
    for row in splits:
        distance = parse_float(row.get("distance_m")) or 0.0
        if distance < 400:
            continue
        pace = parse_float(row.get("pace_min_km"))
        if pace is None:
            moving = parse_float(row.get("moving_time_s"))
            if moving is not None and distance:
                pace = (moving / 60.0) / (distance / 1000.0)
        if pace and 2.5 <= pace <= 12:
            paces.append(pace)
    return paces


def classify_from_splits(split_set: SplitSet) -> str | None:
    """Return intervals/tempo when the split or lap pattern is clear."""
    from_laps = _classify_laps(split_set.laps)
    paces = _km_paces(split_set.splits)
    if len(paces) < 3:
        return from_laps

    local_fast = 0
    for i in range(1, len(paces) - 1):
        if paces[i - 1] - paces[i] >= 0.35 and paces[i + 1] - paces[i] >= 0.35:
            local_fast += 1
    if local_fast >= 2:
        return INTERVALS

    core = paces
    if len(paces) >= 6:
        core = paces[1:-1]
    elif len(paces) >= 4:
        core = paces[1:]
    if len(core) >= 3:
        warmup = paces[0]
        hard = [p for p in core if p <= warmup - 0.35]
        if len(hard) >= 3 and pstdev(hard) <= 0.20:
            return TEMPO
        if pstdev(core) >= 0.40 and (max(core) - min(core)) >= 0.8:
            return INTERVALS
    return from_laps


def _classify_laps(laps: list[dict[str, Any]]) -> str | None:
    if len(laps) < 5:
        return None
    distances = [parse_float(lap.get("distance_m")) or 0.0 for lap in laps]
    paces = [parse_float(lap.get("pace_min_km")) for lap in laps]
    paces = [p for p in paces if p]
    short = [d for d in distances if 200 <= d <= 1200]
    if len(short) >= 5 and len(paces) >= 5:
        med = median(paces)
        fast = sum(1 for p in paces if p <= med - 0.35)
        if fast >= 3:
            return INTERVALS
    names = " ".join(str(lap.get("name") or "") for lap in laps).lower()
    if "interval" in names or "repeat" in names:
        return INTERVALS
    if "tempo" in names or "threshold" in names:
        return TEMPO
    return None


def _is_run(activity_type: str) -> bool:
    return activity_type.lower().replace(" ", "") in SPLIT_RUN_SPORTS or activity_type.lower() == "run"


def _distance_close(a: float | None, b: float | None) -> bool:
    if not a or not b:
        return False
    return abs(a - b) / max(a, b) <= 0.08


def apply_splits_to_sessions(
    sessions: list[Session],
    split_sets: dict[str, SplitSet],
    long_run_min_minutes: int,
) -> list[Session]:
    """Reclassify known runs using splits; add older split-only runs from history."""
    used_ids: set[str] = set()
    for session in sessions:
        matched = _match_split(session, split_sets)
        if not matched:
            continue
        used_ids.add(matched.activity_id)
        session.activity_id = matched.activity_id
        session.splits = matched.splits
        hint = classify_from_splits(matched)
        session.session_type = _reclassify(session, hint, long_run_min_minutes)

    extras: list[Session] = []
    known = {(s.title.lower(), s.when) for s in sessions}
    for split_set in split_sets.values():
        if split_set.activity_id in used_ids or not _is_run(split_set.activity_type):
            continue
        when = split_set.when
        title = split_set.activity_name or "Run"
        if (title.lower(), when) in known:
            continue
        hint = classify_from_splits(split_set)
        duration = split_set.duration_min
        from classify import classify_run

        session_type = classify_run(
            title,
            duration,
            None,
            None,
            long_run_min_minutes,
            splits_hint=hint,
        )
        extras.append(
            Session(
                session_type=session_type,
                title=title,
                sport=split_set.activity_type or "Run",
                when=when,
                duration_min=duration,
                distance_m=split_set.distance_m,
                source="strava_splits",
                activity_id=split_set.activity_id,
                splits=split_set.splits,
            )
        )
    return sessions + extras


def _match_split(session: Session, split_sets: dict[str, SplitSet]) -> SplitSet | None:
    if session.activity_id and session.activity_id in split_sets:
        return split_sets[session.activity_id]
    title = (session.title or "").lower()
    candidates = []
    for split_set in split_sets.values():
        name = split_set.activity_name.lower()
        if title and name and title == name:
            candidates.append(split_set)
            continue
        if _distance_close(session.distance_m, split_set.distance_m) and (
            session.when is None or split_set.when is None or session.when == split_set.when
        ):
            candidates.append(split_set)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _reclassify(session: Session, hint: str | None, long_run_min_minutes: int) -> str:
    from classify import CROSS_TYPES, OTHER, RUN_SPORTS, STRENGTH, classify_run

    if session.session_type == STRENGTH:
        return STRENGTH
    sport_n = (session.sport or "").lower().replace(" ", "")
    if session.session_type in CROSS_TYPES or (
        session.session_type == OTHER and sport_n not in RUN_SPORTS
    ):
        return session.session_type
    return classify_run(
        session.title,
        session.duration_min,
        session.avg_hr,
        session.max_hr,
        long_run_min_minutes,
        splits_hint=hint,
    )
