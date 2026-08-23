"""Persist daily decisions for later feedback / ML."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planner import Plan


def append_decision(path: str, plan: Plan, extra: dict[str, Any] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": plan.session_type,
        "title": plan.recipe.title,
        "details": plan.recipe.details,
        "duration_min": plan.recipe.duration_min,
        "why": plan.why,
        "recovery_band": plan.recovery_band,
        "yesterday": plan.yesterday,
        "week_counts": plan.week_counts,
        "oura_synced_today": plan.oura_synced_today,
    }
    if extra:
        row["extra"] = extra
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    trim_log(target, keep=180)


def trim_log(path: Path, keep: int) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    if len(lines) <= keep:
        return
    path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")
