"""Add-on runtime settings."""

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
    oura_wait_minutes: int = 90
    poll_seconds: int = 60
    notify_service: str = "notify.tg_oskari"
    run_immediately: bool = True
    strava_entity_prefix: str = "sensor.strava_oskari_vuorinen"
    weekly_long_runs: int = 1
    weekly_quality_runs: int = 1
    weekly_strength: int = 2
    weekly_rest_days: int = 1
    long_run_min_minutes: int = 75
    decisions_path: str = "/data/decisions.jsonl"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def notify_domain_service(self) -> tuple[str, str]:
        name = self.notify_service.strip()
        if "." in name:
            domain, service = name.split(".", 1)
            return domain, service
        return "notify", name

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            timezone=os.environ.get("TZ") or os.environ.get("timezone") or "Europe/Helsinki",
            run_time=os.environ.get("RUN_TIME", "07:30"),
            oura_wait_minutes=_env_int("OURA_WAIT_MINUTES", 90),
            poll_seconds=_env_int("POLL_SECONDS", 60),
            notify_service=os.environ.get("NOTIFY_SERVICE", "notify.tg_oskari"),
            run_immediately=_env_bool("RUN_IMMEDIATELY", True),
            strava_entity_prefix=os.environ.get(
                "STRAVA_ENTITY_PREFIX", "sensor.strava_oskari_vuorinen"
            ),
            weekly_long_runs=_env_int("WEEKLY_LONG_RUNS", 1),
            weekly_quality_runs=_env_int("WEEKLY_QUALITY_RUNS", 1),
            weekly_strength=_env_int("WEEKLY_STRENGTH", 2),
            weekly_rest_days=_env_int("WEEKLY_REST_DAYS", 1),
            long_run_min_minutes=_env_int("LONG_RUN_MIN_MINUTES", 75),
            decisions_path=os.environ.get("DECISIONS_PATH", "/data/decisions.jsonl"),
        )
