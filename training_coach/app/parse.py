"""Parsing helpers for Home Assistant states."""

from __future__ import annotations

import math
import re
from datetime import datetime, date
from typing import Any
from zoneinfo import ZoneInfo

UNAVAILABLE = {"", "unknown", "unavailable", "none", "null"}


def is_unavailable(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in UNAVAILABLE


def state_value(entity: dict[str, Any] | None) -> Any:
    if not entity:
        return None
    return entity.get("state")


def attr(entity: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not entity:
        return default
    return (entity.get("attributes") or {}).get(key, default)


def parse_float(value: Any) -> float | None:
    if is_unavailable(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if is_unavailable(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"on", "true", "yes", "1"}:
        return True
    if text in {"off", "false", "no", "0"}:
        return False
    return None


def parse_duration_minutes(value: Any) -> float | None:
    """Accept seconds, minutes, HH:MM:SS, or strings with units."""
    if is_unavailable(value):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        # Values this large are almost certainly seconds.
        if number >= 180:
            return number / 60.0
        return number
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+:\d{2}(:\d{2})?", text):
        parts = [int(p) for p in text.split(":")]
        if len(parts) == 2:
            return parts[0] + parts[1] / 60.0
        return parts[0] * 60 + parts[1] + parts[2] / 60.0
    number = parse_float(text)
    if number is None:
        return None
    if "hour" in text or text.endswith("h"):
        return number * 60.0
    if "sec" in text or text.endswith("s") and "min" not in text:
        return number / 60.0
    if number >= 180:
        return number / 60.0
    return number


def parse_datetime(value: Any, tz: ZoneInfo) -> datetime | None:
    if is_unavailable(value):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_date(value: Any, tz: ZoneInfo) -> date | None:
    dt = parse_datetime(value, tz)
    if dt:
        return dt.date()
    if is_unavailable(value):
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def last_updated(entity: dict[str, Any] | None, tz: ZoneInfo) -> datetime | None:
    if not entity:
        return None
    return parse_datetime(entity.get("last_updated") or entity.get("last_changed"), tz)
