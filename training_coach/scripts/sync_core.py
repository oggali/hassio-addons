#!/usr/bin/env python3
"""Copy training-coach/core into this add-on and reapply the add-on-only edits.

The Home Assistant image only sees files committed in this repo. A symlink to
the other checkout is not there when the image is built. This script is the
link: it copies the other repo's core, then puts back the two edits that
belong only to this install.

Source, first match:

1. ``COACH_CORE_SRC``
2. ``../training-coach/core`` next to this repo
3. ``/home/oskari/git/training-coach/core``

When the source checkout is missing, the script leaves the snapshot as it is
and exits 0. A commit on a machine without that checkout still works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEST = REPO / "training_coach" / "core"
NOTIFY = "notify.telegram_bot_5606541988_90421249"
UPSTREAM_NOTIFY = "notify.tg_oskari"

HOUR_FUNCTION = '''
_HOUR_UNITS = {"h", "hr", "hrs", "hour", "hours"}
_MINUTE_UNITS = {"min", "mins", "minute", "minutes"}


def garmin_recovery_hours(entity: dict[str, Any] | None) -> float | None:
    """Garmin recovery time in hours, read in the sensor's ``unit_of_measurement``.

    Without a known unit, a value above 48 is taken as minutes.
    """
    raw = parse_float(state_value(entity))
    if raw is None:
        return None
    unit = attr(entity, "unit_of_measurement")
    unit_s = "" if is_unavailable(unit) else str(unit).strip().lower()
    if unit_s in _HOUR_UNITS:
        return raw
    if unit_s in _MINUTE_UNITS:
        return raw / 60.0
    return raw / 60.0 if raw > 48 else raw


'''

RECOVERY_BLOCK = """\
    recovery_entity = states.get(GARMIN_RECOVERY_TIME)
    recovery_raw = parse_float(state_value(recovery_entity))
    recovery_unit = attr(recovery_entity, "unit_of_measurement")
    recovery_hours = None
    if recovery_raw is not None:
        if recovery_unit == "h":
            recovery_hours = recovery_raw
        elif recovery_unit == "min" or recovery_raw > 48:
            recovery_hours = recovery_raw / 60.0
        else:
            recovery_hours = recovery_raw
"""

RECOVERY_CALL = "    recovery_hours = garmin_recovery_hours(states.get(GARMIN_RECOVERY_TIME))\n"


def source_dir() -> Path | None:
    candidates = []
    env = os.environ.get("COACH_CORE_SRC", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.append(REPO.parent / "training-coach" / "core")
    candidates.append(Path("/home/oskari/git/training-coach/core"))
    for path in candidates:
        if (path / "pyproject.toml").is_file() and (path / "src" / "coach").is_dir():
            return path
    return None


def ignore_copy(_dir: str, names: list[str]) -> set[str]:
    skipped = set()
    for name in names:
        if name == "__pycache__" or name.endswith(".egg-info") or name == ".pytest_cache":
            skipped.add(name)
        elif name.endswith(".pyc"):
            skipped.add(name)
    return skipped


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def with_newlines(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", newline)


def apply_features(path: Path) -> None:
    raw = path.read_bytes().decode()
    newline = newline_of(raw)
    text = raw.replace("\r\n", "\n")
    if "def garmin_recovery_hours(" not in text:
        marker = "def score_recovery("
        if marker not in text:
            raise SystemExit(f"{path} has no score_recovery; sync_core.py needs an update")
        text = text.replace(marker, HOUR_FUNCTION + marker, 1)
    block = RECOVERY_BLOCK.replace("\n", "\n")
    if block not in text:
        if "garmin_recovery_hours(states.get(GARMIN_RECOVERY_TIME))" not in text:
            raise SystemExit(
                f"{path} recovery-time block changed upstream. Update sync_core.py before copying."
            )
    else:
        text = text.replace(block, RECOVERY_CALL, 1)
    path.write_bytes(with_newlines(text, newline).encode())


def apply_settings(path: Path) -> None:
    raw = path.read_bytes().decode()
    newline = newline_of(raw)
    text = raw.replace("\r\n", "\n")
    if UPSTREAM_NOTIFY not in text:
        if NOTIFY not in text:
            raise SystemExit(
                f"{path} notify default is neither {UPSTREAM_NOTIFY} nor this install. "
                "Update sync_core.py before copying."
            )
    else:
        text = text.replace(UPSTREAM_NOTIFY, NOTIFY)
    path.write_bytes(with_newlines(text, newline).encode())


def upstream_commit(core: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(core.parent), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main() -> int:
    source = source_dir()
    if source is None:
        print(
            "training-coach core not found. Left training_coach/core as it is. "
            "Set COACH_CORE_SRC to the core directory to refresh it.",
            file=sys.stderr,
        )
        return 0
    commit = upstream_commit(source)
    staging = Path(tempfile.mkdtemp(prefix="coach-core-"))
    try:
        copied = staging / "core"
        shutil.copytree(source, copied, ignore=ignore_copy)
        apply_features(copied / "src" / "coach" / "features.py")
        apply_settings(copied / "src" / "coach" / "settings.py")
        (copied / "UPSTREAM").write_text(
            "source: https://github.com/oggali/training-coach\n"
            f"commit: {commit}\n"
            "path: core\n"
            "Reapplied after copy: garmin_recovery_hours unit names, "
            f"notify_service {NOTIFY}.\n",
            encoding="utf-8",
        )
        previous = DEST.with_name("core.previous")
        if previous.exists():
            shutil.rmtree(previous)
        if DEST.exists():
            DEST.rename(previous)
        try:
            shutil.move(str(copied), str(DEST))
        except Exception:
            if previous.exists() and not DEST.exists():
                previous.rename(DEST)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"Refreshed training_coach/core from {source} at {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
