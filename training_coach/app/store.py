"""DuckDB store for normalized coaching facts."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from classify import Session
from features import Recovery
from planner import Plan
from settings import Settings

SCHEMA_VERSION = "1"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR
);

CREATE TABLE IF NOT EXISTS sessions (
    session_key VARCHAR PRIMARY KEY,
    activity_id VARCHAR,
    session_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    sport VARCHAR NOT NULL,
    when_day DATE,
    duration_min DOUBLE,
    distance_m DOUBLE,
    avg_hr DOUBLE,
    max_hr DOUBLE,
    source VARCHAR NOT NULL,
    splits_json VARCHAR,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_daily (
    day DATE PRIMARY KEY,
    band VARCHAR NOT NULL,
    rest_mode BOOLEAN NOT NULL,
    oura_readiness DOUBLE,
    oura_sleep DOUBLE,
    oura_hrv DOUBLE,
    oura_hrv_balance DOUBLE,
    oura_temp DOUBLE,
    garmin_readiness DOUBLE,
    garmin_readiness_text VARCHAR,
    garmin_body_battery DOUBLE,
    garmin_recovery_hours DOUBLE,
    garmin_hrv_status VARCHAR,
    garmin_hrv_ratio DOUBLE,
    reasons_json VARCHAR,
    oura_synced_today BOOLEAN NOT NULL,
    already_trained_today BOOLEAN NOT NULL,
    captured_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    day DATE PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    session_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    details VARCHAR NOT NULL,
    duration_min INTEGER NOT NULL,
    why VARCHAR NOT NULL,
    recovery_band VARCHAR NOT NULL,
    yesterday VARCHAR,
    week_counts_json VARCHAR,
    oura_synced_today BOOLEAN NOT NULL,
    settings_json VARCHAR,
    session_keys_json VARCHAR,
    extra_json VARCHAR
);
"""


def session_key(session: Session) -> str:
    if session.activity_id:
        return f"id:{session.activity_id}"
    when = session.when.isoformat() if session.when else "none"
    return f"title:{session.title}|{when}"


class CoachStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self.path))
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CoachStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def migrate(self) -> None:
        self._conn.execute(_SCHEMA_SQL)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            ["schema_version", SCHEMA_VERSION],
        )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", [key]
        ).fetchone()
        return None if row is None else row[0]

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)", [key, value]
        )

    def session_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0]) if row else 0

    def needs_history_seed(self) -> bool:
        if self.session_count() == 0:
            return True
        return self.get_meta("last_history_seed_at") is None

    def mark_history_seeded(self) -> None:
        self.set_meta(
            "last_history_seed_at",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def upsert_sessions(self, sessions: list[Session]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for session in sessions:
            key = session_key(session)
            splits_json = None
            if session.splits is not None:
                splits_json = json.dumps(session.splits, ensure_ascii=False)
            self._conn.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    session_key, activity_id, session_type, title, sport, when_day,
                    duration_min, distance_m, avg_hr, max_hr, source, splits_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    key,
                    session.activity_id,
                    session.session_type,
                    session.title,
                    session.sport,
                    session.when,
                    session.duration_min,
                    session.distance_m,
                    session.avg_hr,
                    session.max_hr,
                    session.source,
                    splits_json,
                    now,
                ],
            )
            count += 1
        return count

    def load_sessions(self, since: date | None = None) -> list[Session]:
        if since is None:
            rows = self._conn.execute(
                """
                SELECT activity_id, session_type, title, sport, when_day,
                       duration_min, distance_m, avg_hr, max_hr, source, splits_json
                FROM sessions
                ORDER BY when_day DESC NULLS LAST
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT activity_id, session_type, title, sport, when_day,
                       duration_min, distance_m, avg_hr, max_hr, source, splits_json
                FROM sessions
                WHERE when_day IS NULL OR when_day >= ?
                ORDER BY when_day DESC NULLS LAST
                """,
                [since],
            ).fetchall()
        out: list[Session] = []
        for row in rows:
            splits = None
            if row[10]:
                splits = json.loads(row[10])
            out.append(
                Session(
                    activity_id=row[0],
                    session_type=row[1],
                    title=row[2],
                    sport=row[3],
                    when=row[4],
                    duration_min=row[5],
                    distance_m=row[6],
                    avg_hr=row[7],
                    max_hr=row[8],
                    source=row[9],
                    splits=splits,
                )
            )
        return out

    def upsert_recovery(
        self,
        day: date,
        recovery: Recovery,
        *,
        oura_synced_today: bool,
        already_trained_today: bool,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO recovery_daily (
                day, band, rest_mode, oura_readiness, oura_sleep, oura_hrv,
                oura_hrv_balance, oura_temp, garmin_readiness, garmin_readiness_text,
                garmin_body_battery, garmin_recovery_hours, garmin_hrv_status,
                garmin_hrv_ratio, reasons_json, oura_synced_today, already_trained_today,
                captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                day,
                recovery.band,
                recovery.rest_mode,
                recovery.oura_readiness,
                recovery.oura_sleep,
                recovery.oura_hrv,
                recovery.oura_hrv_balance,
                recovery.oura_temp,
                recovery.garmin_readiness,
                recovery.garmin_readiness_text,
                recovery.garmin_body_battery,
                recovery.garmin_recovery_hours,
                recovery.garmin_hrv_status,
                recovery.garmin_hrv_ratio,
                json.dumps(recovery.reasons, ensure_ascii=False),
                oura_synced_today,
                already_trained_today,
                datetime.now(timezone.utc),
            ],
        )

    def upsert_decision(
        self,
        day: date,
        plan: Plan,
        settings: Settings,
        sessions: list[Session],
        extra: dict[str, Any] | None = None,
    ) -> None:
        settings_json = json.dumps(
            {
                "timezone": settings.timezone,
                "weekly_long_runs": settings.weekly_long_runs,
                "weekly_quality_runs": settings.weekly_quality_runs,
                "weekly_strength": settings.weekly_strength,
                "weekly_rest_days": settings.weekly_rest_days,
                "long_run_min_minutes": settings.long_run_min_minutes,
            },
            ensure_ascii=False,
        )
        week_start = day.fromordinal(day.toordinal() - 6)
        session_keys = [session_key(s) for s in sessions if s.when and s.when >= week_start]
        self._conn.execute(
            """
            INSERT OR REPLACE INTO decisions (
                day, ts, session_type, title, details, duration_min, why,
                recovery_band, yesterday, week_counts_json, oura_synced_today,
                settings_json, session_keys_json, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                day,
                datetime.now(timezone.utc),
                plan.session_type,
                plan.recipe.title,
                plan.recipe.details,
                plan.recipe.duration_min,
                plan.why,
                plan.recovery_band,
                plan.yesterday,
                json.dumps(plan.week_counts, ensure_ascii=False),
                plan.oura_synced_today,
                settings_json,
                json.dumps(session_keys, ensure_ascii=False),
                json.dumps(extra or {}, ensure_ascii=False),
            ],
        )

    def wipe(self) -> None:
        """Delete the database file and reopen an empty schema."""
        self._conn.close()
        for suffix in ("", ".wal"):
            target = Path(str(self.path) + suffix) if suffix else self.path
            if target.exists():
                target.unlink()
        # DuckDB may also leave .tmp files; clear siblings with same stem.
        for sibling in self.path.parent.glob(self.path.name + "*"):
            if sibling.is_file():
                sibling.unlink()
        self._conn = duckdb.connect(str(self.path))
        self.migrate()
