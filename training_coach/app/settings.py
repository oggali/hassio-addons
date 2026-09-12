"""Add-on runtime settings (ops only; training intent lives in helpers / DuckDB)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    timezone: str = "Europe/Helsinki"
    run_time: str = "07:30"
    evening_time: str = "20:30"
    oura_wait_minutes: int = 90
    poll_seconds: int = 60
    notify_service: str = "notify.tg_oskari"
    mobile_notify_service: str = ""
    run_immediately: bool = True
    strava_entity_prefix: str = "sensor.strava_oskari_vuorinen"
    long_run_min_minutes: int = 75
    db_path: str = "/data/coach.duckdb"
    history_seed_days: int = 365

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def mobile_enabled(self) -> bool:
        value = (self.mobile_notify_service or "").strip().lower()
        return bool(value) and value not in {"null", "none", "unknown", "false"}

    @property
    def notify_domain_service(self) -> tuple[str, str]:
        return _split_service(self.notify_service, "notify")

    @property
    def mobile_domain_service(self) -> tuple[str, str] | None:
        if not self.mobile_enabled:
            return None
        return _split_service(self.mobile_notify_service, "notify")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            timezone=os.environ.get("TZ") or os.environ.get("timezone") or "Europe/Helsinki",
            run_time=os.environ.get("RUN_TIME", "07:30"),
            evening_time=os.environ.get("EVENING_TIME", "20:30"),
            oura_wait_minutes=_env_int("OURA_WAIT_MINUTES", 90),
            poll_seconds=_env_int("POLL_SECONDS", 60),
            notify_service=os.environ.get("NOTIFY_SERVICE", "notify.tg_oskari"),
            mobile_notify_service=os.environ.get("MOBILE_NOTIFY_SERVICE", "") or "",
            run_immediately=_env_bool("RUN_IMMEDIATELY", True),
            strava_entity_prefix=os.environ.get(
                "STRAVA_ENTITY_PREFIX", "sensor.strava_oskari_vuorinen"
            ),
            long_run_min_minutes=_env_int("LONG_RUN_MIN_MINUTES", 75),
            db_path=os.environ.get("DB_PATH", "/data/coach.duckdb"),
            history_seed_days=_env_int("HISTORY_SEED_DAYS", 365),
        )


def _split_service(name: str, default_domain: str) -> tuple[str, str]:
    text = name.strip()
    if "." in text:
        domain, service = text.split(".", 1)
        return domain, service
    return default_domain, text
