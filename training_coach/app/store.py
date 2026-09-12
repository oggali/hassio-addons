"""DuckDB store for normalized coaching facts."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from classify import Session
from features import Recovery
from goal import Prefs, normalize_race_distance
from planner import Plan
from settings import Settings

SCHEMA_VERSION = "2"


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None

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

CREATE TABLE IF NOT EXISTS prefs_history (
    id INTEGER PRIMARY KEY,
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP,
    race_date DATE,
    race_distance VARCHAR NOT NULL,
    target_time VARCHAR,
    weekly_long_runs INTEGER NOT NULL,
    weekly_quality_runs INTEGER NOT NULL,
    weekly_strength INTEGER NOT NULL,
    weekly_rest_days INTEGER NOT NULL,
    source VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    payload_json VARCHAR
);

CREATE TABLE IF NOT EXISTS plan_days (
    day DATE PRIMARY KEY,
    session_type VARCHAR NOT NULL,
    km_min DOUBLE,
    km_max DOUBLE,
    pace_min DOUBLE,
    pace_max DOUBLE,
    structure VARCHAR,
    phase VARCHAR,
    source VARCHAR,
    extra_json VARCHAR,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_history (
    day DATE PRIMARY KEY,
    planned_type VARCHAR,
    actual_type VARCHAR,
    compliance VARCHAR,
    feeling VARCHAR,
    skip_reason VARCHAR,
    recovery_band VARCHAR,
    source VARCHAR,
    notes VARCHAR,
    updated_at TIMESTAMP NOT NULL
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
                "prefs": extra.get("prefs") if extra else None,
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

    def get_decision(self, day: date) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT session_type, title, details, duration_min, why, recovery_band,
                   yesterday, extra_json
            FROM decisions WHERE day = ?
            """,
            [day],
        ).fetchone()
        if row is None:
            return None
        extra = json.loads(row[7]) if row[7] else {}
        return {
            "session_type": row[0],
            "title": row[1],
            "details": row[2],
            "duration_min": row[3],
            "why": row[4],
            "recovery_band": row[5],
            "yesterday": row[6],
            "extra": extra,
        }

    def _next_prefs_id(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM prefs_history").fetchone()
        return int(row[0]) if row else 1

    def current_prefs(self) -> Prefs | None:
        row = self._conn.execute(
            """
            SELECT id, race_date, race_distance, target_time, weekly_long_runs,
                   weekly_quality_runs, weekly_strength, weekly_rest_days, source
            FROM prefs_history
            WHERE valid_to IS NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return Prefs(
            race_date=_as_date(row[1]),
            race_distance=normalize_race_distance(row[2]),
            target_time=row[3] or "",
            weekly_long_runs=int(row[4]),
            weekly_quality_runs=int(row[5]),
            weekly_strength=int(row[6]),
            weekly_rest_days=int(row[7]),
            source=row[8] or "seed",
            prefs_id=int(row[0]),
        )

    def insert_prefs(self, prefs: Prefs) -> Prefs:
        now = datetime.now(timezone.utc)
        current = self.current_prefs()
        if current is not None and current.fingerprint == prefs.fingerprint:
            return current
        if current is not None:
            self._conn.execute(
                "UPDATE prefs_history SET valid_to = ? WHERE valid_to IS NULL",
                [now],
            )
        new_id = self._next_prefs_id()
        self._conn.execute(
            """
            INSERT INTO prefs_history (
                id, valid_from, valid_to, race_date, race_distance, target_time,
                weekly_long_runs, weekly_quality_runs, weekly_strength, weekly_rest_days,
                source, fingerprint, payload_json
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                new_id,
                now,
                prefs.race_date,
                prefs.race_distance,
                prefs.target_time,
                prefs.weekly_long_runs,
                prefs.weekly_quality_runs,
                prefs.weekly_strength,
                prefs.weekly_rest_days,
                prefs.source,
                prefs.fingerprint,
                json.dumps(prefs.as_dict(), ensure_ascii=False, default=str),
            ],
        )
        return Prefs(
            race_date=prefs.race_date,
            race_distance=prefs.race_distance,
            target_time=prefs.target_time,
            weekly_long_runs=prefs.weekly_long_runs,
            weekly_quality_runs=prefs.weekly_quality_runs,
            weekly_strength=prefs.weekly_strength,
            weekly_rest_days=prefs.weekly_rest_days,
            source=prefs.source,
            prefs_id=new_id,
        )

    def replace_plan_days(self, days: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        self._conn.execute("DELETE FROM plan_days")
        for item in days:
            self._conn.execute(
                """
                INSERT INTO plan_days (
                    day, session_type, km_min, km_max, pace_min, pace_max,
                    structure, phase, source, extra_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item["day"],
                    item["session_type"],
                    item.get("km_min"),
                    item.get("km_max"),
                    item.get("pace_min"),
                    item.get("pace_max"),
                    item.get("structure") or "",
                    item.get("phase") or "",
                    item.get("source") or "skeleton",
                    json.dumps(item.get("extra") or {}, ensure_ascii=False),
                    now,
                ],
            )

    def load_plan_days(self, since: date | None = None) -> list[dict[str, Any]]:
        if since is None:
            rows = self._conn.execute(
                """
                SELECT day, session_type, km_min, km_max, pace_min, pace_max,
                       structure, phase, source, extra_json
                FROM plan_days
                ORDER BY day
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT day, session_type, km_min, km_max, pace_min, pace_max,
                       structure, phase, source, extra_json
                FROM plan_days
                WHERE day >= ?
                ORDER BY day
                """,
                [since],
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            extra = json.loads(row[9]) if row[9] else {}
            out.append(
                {
                    "day": _as_date(row[0]),
                    "session_type": row[1],
                    "km_min": row[2],
                    "km_max": row[3],
                    "pace_min": row[4],
                    "pace_max": row[5],
                    "structure": row[6] or "",
                    "phase": row[7] or "",
                    "source": row[8] or "",
                    "extra": extra,
                }
            )
        return out

    def get_plan_day(self, day: date) -> dict[str, Any] | None:
        for item in self.load_plan_days(since=day):
            if item["day"] == day:
                return item
        return None

    def upsert_feedback(
        self,
        day: date,
        *,
        planned_type: str | None = None,
        actual_type: str | None = None,
        compliance: str | None = None,
        feeling: str | None = None,
        skip_reason: str | None = None,
        recovery_band: str | None = None,
        source: str = "system",
        notes: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_feedback(day) or {}
        payload = {
            "planned_type": planned_type if planned_type is not None else existing.get("planned_type"),
            "actual_type": actual_type if actual_type is not None else existing.get("actual_type"),
            "compliance": compliance if compliance is not None else existing.get("compliance"),
            "feeling": feeling if feeling is not None else existing.get("feeling"),
            "skip_reason": skip_reason if skip_reason is not None else existing.get("skip_reason"),
            "recovery_band": recovery_band
            if recovery_band is not None
            else existing.get("recovery_band"),
            "source": source or existing.get("source") or "system",
            "notes": notes if notes is not None else existing.get("notes"),
        }
        self._conn.execute(
            """
            INSERT OR REPLACE INTO feedback_history (
                day, planned_type, actual_type, compliance, feeling, skip_reason,
                recovery_band, source, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                day,
                payload["planned_type"],
                payload["actual_type"],
                payload["compliance"],
                payload["feeling"],
                payload["skip_reason"],
                payload["recovery_band"],
                payload["source"],
                payload["notes"],
                datetime.now(timezone.utc),
            ],
        )
        payload["day"] = day
        return payload

    def get_feedback(self, day: date) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT planned_type, actual_type, compliance, feeling, skip_reason,
                   recovery_band, source, notes
            FROM feedback_history WHERE day = ?
            """,
            [day],
        ).fetchone()
        if row is None:
            return None
        return {
            "day": day,
            "planned_type": row[0],
            "actual_type": row[1],
            "compliance": row[2],
            "feeling": row[3],
            "skip_reason": row[4],
            "recovery_band": row[5],
            "source": row[6],
            "notes": row[7],
        }

    def load_feedback(self, since: date | None = None) -> list[dict[str, Any]]:
        if since is None:
            rows = self._conn.execute(
                """
                SELECT day, planned_type, actual_type, compliance, feeling, skip_reason,
                       recovery_band, source, notes
                FROM feedback_history
                ORDER BY day
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT day, planned_type, actual_type, compliance, feeling, skip_reason,
                       recovery_band, source, notes
                FROM feedback_history
                WHERE day >= ?
                ORDER BY day
                """,
                [since],
            ).fetchall()
        return [
            {
                "day": _as_date(row[0]),
                "planned_type": row[1],
                "actual_type": row[2],
                "compliance": row[3],
                "feeling": row[4],
                "skip_reason": row[5],
                "recovery_band": row[6],
                "source": row[7],
                "notes": row[8],
            }
            for row in rows
        ]

    def load_recovery_bands(self, since: date | None = None) -> list[str]:
        if since is None:
            rows = self._conn.execute("SELECT band FROM recovery_daily ORDER BY day").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT band FROM recovery_daily WHERE day >= ? ORDER BY day",
                [since],
            ).fetchall()
        return [row[0] for row in rows if row and row[0]]

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
