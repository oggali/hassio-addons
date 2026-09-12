"""Race goal parsing: distance, target time, weeks/phase."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta

RACE_NONE = "none"
RACE_5K = "5k"
RACE_10K = "10k"
RACE_HALF = "half"
RACE_MARATHON = "marathon"
RACE_DISTANCES = (RACE_NONE, RACE_5K, RACE_10K, RACE_HALF, RACE_MARATHON)

RACE_KM = {
    RACE_5K: 5.0,
    RACE_10K: 10.0,
    RACE_HALF: 21.0975,
    RACE_MARATHON: 42.195,
}

FEELING_OPTIONS = ("unset", "great", "ok", "tired", "wiped")
DID_PLAN_OPTIONS = ("unset", "yes", "modified", "skipped")
SKIP_REASON_OPTIONS = ("unset", "no_time", "tired", "sore", "weather", "other_sport")


@dataclass(frozen=True)
class Prefs:
    race_date: date | None = None
    race_distance: str = RACE_NONE
    target_time: str = ""
    weekly_long_runs: int = 1
    weekly_quality_runs: int = 1
    weekly_strength: int = 2
    weekly_rest_days: int = 1
    source: str = "seed"
    prefs_id: int | None = None

    @classmethod
    def defaults(cls) -> "Prefs":
        return cls()

    @property
    def has_race(self) -> bool:
        return self.race_distance in RACE_KM and self.race_date is not None

    @property
    def race_km(self) -> float | None:
        return RACE_KM.get(self.race_distance)

    @property
    def target_seconds(self) -> float | None:
        return parse_target_seconds(self.target_time)

    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            [
                self.race_date.isoformat() if self.race_date else "",
                self.race_distance,
                self.target_time.strip(),
                str(self.weekly_long_runs),
                str(self.weekly_quality_runs),
                str(self.weekly_strength),
                str(self.weekly_rest_days),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {
            "race_date": self.race_date.isoformat() if self.race_date else None,
            "race_distance": self.race_distance,
            "target_time": self.target_time,
            "target_seconds": self.target_seconds,
            "weekly_long_runs": self.weekly_long_runs,
            "weekly_quality_runs": self.weekly_quality_runs,
            "weekly_strength": self.weekly_strength,
            "weekly_rest_days": self.weekly_rest_days,
            "fingerprint": self.fingerprint,
            "source": self.source,
            "prefs_id": self.prefs_id,
        }


def normalize_race_distance(value: str | None) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "none": RACE_NONE,
        "": RACE_NONE,
        "5k": RACE_5K,
        "5": RACE_5K,
        "5000": RACE_5K,
        "10k": RACE_10K,
        "10": RACE_10K,
        "10000": RACE_10K,
        "half": RACE_HALF,
        "half_marathon": RACE_HALF,
        "hm": RACE_HALF,
        "marathon": RACE_MARATHON,
        "mara": RACE_MARATHON,
        "42k": RACE_MARATHON,
    }
    return aliases.get(text, RACE_NONE)


def parse_target_seconds(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "unavailable", "none", "unset"}:
        return None
    if re.fullmatch(r"\d+:\d{2}(:\d{2})?", text):
        parts = [int(p) for p in text.split(":")]
        if len(parts) == 2:
            if parts[0] >= 5:
                return parts[0] * 60 + parts[1]
            return parts[0] * 3600 + parts[1] * 60
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0:
        return None
    if number < 400:
        return number * 60
    return number


def format_hms(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return ""
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_race_date(value: str | None, today: date | None = None) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "unavailable", "none", "unset"}:
        return None
    text = text[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    if parsed.year < 2000:
        return None
    return parsed


def days_to_race(today: date, race_date: date | None) -> int | None:
    if race_date is None:
        return None
    return (race_date - today).days


def weeks_to_race(today: date, race_date: date | None) -> float | None:
    remaining = days_to_race(today, race_date)
    if remaining is None:
        return None
    return remaining / 7.0


def phase_for(day: date, prefs: Prefs) -> str:
    """base → build → peak → taper → race, from days left.

    Short races taper 10 days, half/marathon 14. Peak is the 3 weeks before
    taper; build is the 7 weeks before peak. Lengthen taper_days if you like a
    longer wind-down; the skeleton shortens quality/long automatically in taper.
    """
    if not prefs.has_race or prefs.race_date is None:
        return "base"
    left = (prefs.race_date - day).days
    if left <= 0:
        return "race"
    taper_days = 10 if prefs.race_distance in {RACE_5K, RACE_10K} else 14
    if left <= taper_days:
        return "taper"
    if left <= taper_days + 21:  # ~3 weeks peak
        return "peak"
    if left <= taper_days + 49:  # ~7 weeks build
        return "build"
    return "base"


def clamp_int(value: float | int | None, default: int, lo: int, hi: int) -> int:
    if value is None:
        return default
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def end_of_plan(today: date, prefs: Prefs) -> date:
    if prefs.has_race and prefs.race_date and prefs.race_date >= today:
        return prefs.race_date
    return today + timedelta(days=13)
