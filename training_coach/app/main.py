"""Morning / evening training coach loop."""

from __future__ import annotations

import json
import os
import select
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from entities import (
    FEEDBACK_SENSOR,
    GOAL_SENSOR,
    SESSION_SENSOR,
    STRAVA_LATEST_SPLITS,
    SUMMARY_SENSOR,
    tracked_entity_ids,
)
from features import build_snapshot, collect_live_sessions
from feedback import (
    android_actions,
    android_followups,
    classify_compliance,
    coaching_note,
    describe_next_session,
    parse_coach_action,
    primary_actual,
    recap_text,
    resolve_tomorrow_row,
)
from goal import Prefs, days_to_race, format_hms, phase_for
from ha_client import HomeAssistantClient
from ha_ws import parse_action_day, run_action_listener, websocket_url
from load import build_load_snapshot
from paces import build_paces, format_pace_range
from periodize import PlanDay, build_skeleton
from planner import Plan, plan_day
from prefs import PrefsManager
from recipes import format_km_range
from settings import Settings
from simulate import finish_distribution, search_calendar
from store import CoachStore


def log(message: str) -> None:
    print(f"[training_coach] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.strip().split(":")
    return int(hour), int(minute)


def at_time(now: datetime, hhmm: str) -> datetime:
    hour, minute = parse_hhmm(hhmm)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_named_event(now: datetime, settings: Settings) -> tuple[datetime, str]:
    morning = at_time(now, settings.run_time)
    evening = at_time(now, settings.evening_time)
    events = []
    if morning > now:
        events.append((morning, "morning"))
    else:
        events.append((morning + timedelta(days=1), "morning"))
    if evening > now:
        events.append((evening, "evening"))
    else:
        events.append((evening + timedelta(days=1), "evening"))
    events.sort(key=lambda item: item[0])
    return events[0]


def should_fire_named_event(
    now: datetime,
    target: datetime,
    kind: str,
    last_fired: tuple[date, str] | None,
) -> bool:
    """Fire only after the slot arrives, and only once per local day."""
    if now < target:
        return False
    return last_fired != (now.date(), kind)


def consume_daily_notify(store: CoachStore, day: date, kind: str) -> bool:
    """Claim today's morning/evening notify. False if it was already sent."""
    key = f"last_notify_{kind}"
    token = day.isoformat()
    if store.get_meta(key) == token:
        return False
    store.set_meta(key, token)
    return True


def morning_slot_passed(now: datetime, settings: Settings) -> bool:
    return now >= at_time(now, settings.run_time)


def wait_for_oura(client: HomeAssistantClient, settings: Settings) -> dict:
    deadline = datetime.now(settings.tz) + timedelta(minutes=settings.oura_wait_minutes)
    entity_ids = tracked_entity_ids(settings.strava_entity_prefix)
    last_states: dict = {}
    while True:
        last_states = client.get_states(entity_ids)
        snapshot = build_snapshot(last_states, settings)
        if snapshot.oura_synced_today:
            log("Oura readiness looks updated for today")
            return last_states
        if datetime.now(settings.tz) >= deadline:
            log("Timed out waiting for Oura sync; planning with current states")
            return last_states
        log("Waiting for Oura sync...")
        time.sleep(max(5, settings.poll_seconds))


def seed_history(client: HomeAssistantClient, settings: Settings, store: CoachStore) -> int:
    start = datetime.now(settings.tz) - timedelta(days=settings.history_seed_days)
    entity_ids = [
        f"{settings.strava_entity_prefix}_run_date",
        f"{settings.strava_entity_prefix}_weight_training_date",
    ]
    history = None
    split_hist = None
    try:
        history = client.get_history(entity_ids, start)
    except Exception as exc:  # noqa: BLE001
        log(f"History seed (dates) failed: {exc}")
    try:
        split_hist = client.get_history(
            [STRAVA_LATEST_SPLITS],
            start,
            include_attributes=True,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"History seed (splits) failed: {exc}")
    states = client.get_states(tracked_entity_ids(settings.strava_entity_prefix))
    sessions = collect_live_sessions(states, settings, history=history, split_history=split_hist)
    n = store.upsert_sessions(sessions)
    store.mark_history_seeded()
    log(f"Seeded {n} sessions from HA history ({settings.history_seed_days}d lookback)")
    return n


def upcoming_payload(days: list[PlanDay], today: date, limit: int = 7) -> list[dict]:
    out: list[dict] = []
    for item in days:
        if item.day <= today:
            continue
        out.append(
            {
                "day": item.day.isoformat(),
                "weekday": item.day.strftime("%a"),
                "session": item.session_type,
                "km": format_km_range(item.km_min, item.km_max),
                "pace": format_pace_range(item.pace_min, item.pace_max),
                "structure": item.structure,
                "phase": item.phase,
                "line": (
                    f"{item.day.strftime('%a')}: {item.session_type.replace('_', ' ')} "
                    f"{format_km_range(item.km_min, item.km_max)}"
                    + (
                        f" @ {format_pace_range(item.pace_min, item.pace_max)}"
                        if item.pace_min
                        else ""
                    )
                ).strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


def dicts_to_plan_days(rows: list[dict]) -> list[PlanDay]:
    days: list[PlanDay] = []
    for row in rows:
        day = row["day"]
        if isinstance(day, str):
            day = date.fromisoformat(day)
        days.append(
            PlanDay(
                day=day,
                session_type=row["session_type"],
                km_min=float(row.get("km_min") or 0),
                km_max=float(row.get("km_max") or 0),
                pace_min=row.get("pace_min"),
                pace_max=row.get("pace_max"),
                structure=row.get("structure") or "",
                phase=row.get("phase") or "",
                source=row.get("source") or "",
            )
        )
    return days


def rebuild_calendar(store: CoachStore, snapshot, prefs: Prefs, feeling: str | None) -> tuple[list[PlanDay], Any, Any, dict]:
    load = build_load_snapshot(snapshot.sessions, snapshot.today)
    paces = build_paces(snapshot.sessions, prefs, snapshot.today)
    last_compliance = None
    for session in sorted(snapshot.sessions, key=lambda s: s.when or date.min, reverse=True):
        if session.session_type in {"intervals", "tempo"} and session.when:
            row = store.get_feedback(session.when)
            if row:
                last_compliance = row.get("compliance")
            break
    skeleton = build_skeleton(
        snapshot.today, prefs, load, paces, snapshot.sessions, feeling, last_compliance
    )
    finish = finish_distribution(paces, prefs, seed=int(prefs.fingerprint[:8], 16) % 100000)
    feedback = store.load_feedback(since=snapshot.today - timedelta(days=120))
    chosen = search_calendar(skeleton, load, prefs, paces, feedback, finish)
    store.replace_plan_days([d.as_dict() for d in chosen])
    store.set_meta("plan_fingerprint", prefs.fingerprint)
    return chosen, load, paces, finish


def publish_plan(client: HomeAssistantClient, plan: Plan) -> None:
    attributes = {
        "friendly_name": "Training coach session",
        "icon": "mdi:run-fast" if plan.session_type != "rest" else "mdi:bed",
        "title": plan.recipe.title,
        "details": plan.recipe.details,
        "duration_min": plan.recipe.duration_min,
        "km_min": plan.recipe.km_min,
        "km_max": plan.recipe.km_max,
        "pace_min": plan.recipe.pace_min,
        "pace_max": plan.recipe.pace_max,
        "structure": plan.recipe.structure,
        "why": plan.why,
        "recovery_band": plan.recovery_band,
        "yesterday": plan.yesterday,
        "week_counts": plan.week_counts,
        "oura_synced_today": plan.oura_synced_today,
        "upcoming": plan.upcoming,
        "phase": plan.phase,
    }
    client.set_state(SESSION_SENSOR, plan.session_type, attributes)
    client.set_state(
        SUMMARY_SENSOR,
        plan.recipe.title,
        {
            "friendly_name": "Training coach summary",
            "icon": "mdi:text-box-outline",
            "text": plan.summary,
            "session": plan.session_type,
            "why": plan.why,
            "upcoming": plan.upcoming,
        },
    )


def publish_goal(
    client: HomeAssistantClient,
    prefs: Prefs,
    today: date,
    load,
    finish: dict,
    phase: str | None,
) -> None:
    p50 = finish.get("p50")
    state = format_hms(p50) if p50 else (prefs.race_distance if prefs.has_race else "none")
    client.set_state(
        GOAL_SENSOR,
        state or "none",
        {
            "friendly_name": "Training coach goal",
            "icon": "mdi:flag-checkered",
            "race_date": prefs.race_date.isoformat() if prefs.race_date else None,
            "race_distance": prefs.race_distance,
            "target_time": prefs.target_time,
            "days_to_race": days_to_race(today, prefs.race_date),
            "predicted_p10": format_hms(finish.get("p10")),
            "predicted_p50": format_hms(finish.get("p50")),
            "predicted_p90": format_hms(finish.get("p90")),
            "p_hit": finish.get("p_hit"),
            "feasible": finish.get("feasible"),
            "phase": phase,
            "ctl": round(load.ctl, 1) if load else None,
            "atl": round(load.atl, 1) if load else None,
            "tsb": round(load.tsb, 1) if load else None,
            "weekly_km": round(load.weekly_km, 1) if load else None,
            "fingerprint": prefs.fingerprint,
            "weekly_long_runs": prefs.weekly_long_runs,
            "weekly_quality_runs": prefs.weekly_quality_runs,
            "weekly_strength": prefs.weekly_strength,
            "weekly_rest_days": prefs.weekly_rest_days,
        },
    )


def publish_feedback_sensor(client: HomeAssistantClient, row: dict | None) -> None:
    if not row:
        client.set_state(
            FEEDBACK_SENSOR,
            "none",
            {"friendly_name": "Training coach feedback", "icon": "mdi:comment-quote-outline"},
        )
        return
    client.set_state(
        FEEDBACK_SENSOR,
        row.get("compliance") or row.get("feeling") or "pending",
        {
            "friendly_name": "Training coach feedback",
            "icon": "mdi:comment-quote-outline",
            **{k: v for k, v in row.items() if k != "day"},
            "day": row["day"].isoformat() if hasattr(row.get("day"), "isoformat") else row.get("day"),
        },
    )


def notify_message(
    client: HomeAssistantClient,
    settings: Settings,
    title: str,
    message: str,
    *,
    android_data: dict | None = None,
    telegram: bool = True,
    android: bool = True,
) -> None:
    if telegram:
        domain, service = settings.notify_domain_service
        try:
            client.call_service(domain, service, {"message": message, "title": title})
            log(f"Notified via {domain}.{service}")
        except Exception as exc:  # noqa: BLE001
            log(f"Notify failed: {exc}")
    if android and settings.mobile_domain_service:
        domain, service = settings.mobile_domain_service
        payload: dict[str, Any] = {"message": message, "title": title}
        if android_data:
            payload["data"] = android_data
        try:
            client.call_service(domain, service, payload)
            log(f"Notified via {domain}.{service}")
        except Exception as exc:  # noqa: BLE001
            log(f"Mobile notify failed: {exc}")


def notify_plan(client: HomeAssistantClient, settings: Settings, plan: Plan) -> None:
    upcoming = ""
    if plan.upcoming:
        upcoming = "\n\nUpcoming:\n" + "\n".join(item.get("line", "") for item in plan.upcoming[:7])
    message = (
        f"Today: {plan.recipe.title}\n"
        f"{plan.recipe.details}\n\n"
        f"Why: {plan.why}\n"
        f"Recovery: {plan.recovery_band}"
        f"{upcoming}"
    )
    notify_message(client, settings, "Training coach", message)


def ingest(client: HomeAssistantClient, settings: Settings, store: CoachStore, wait_oura: bool):
    if wait_oura:
        states = wait_for_oura(client, settings)
    else:
        states = client.get_states(tracked_entity_ids(settings.strava_entity_prefix))
    live = collect_live_sessions(states, settings)
    store.upsert_sessions(live)
    log(f"Upserted {len(live)} live sessions")
    if store.needs_history_seed():
        seed_history(client, settings, store)
        states = client.get_states(tracked_entity_ids(settings.strava_entity_prefix))
    sessions = store.load_sessions()
    snapshot = build_snapshot(states, settings, sessions=sessions)
    return states, snapshot


def reconcile_yesterday(store: CoachStore, snapshot) -> None:
    yesterday = snapshot.today - timedelta(days=1)
    fb = store.get_feedback(yesterday)
    if not fb or fb.get("compliance") != "skipped":
        return
    actual = primary_actual(snapshot.sessions, yesterday)
    if not actual:
        return
    compliance = classify_compliance(fb.get("planned_type"), actual)
    store.upsert_feedback(
        yesterday,
        actual_type=actual,
        compliance=compliance,
        source="late_session",
    )
    log(f"Updated yesterday feedback to {compliance} after late session")


def capture_feedback_helpers(store: CoachStore, manager: PrefsManager, day: date) -> None:
    states = manager.load_helper_states()
    from prefs import read_feedback_helpers

    values = read_feedback_helpers(states)
    if all(v == "unset" for v in values.values()):
        return
    existing = store.get_feedback(day) or {}
    compliance = existing.get("compliance")
    if values["did_plan"] == "skipped":
        compliance = "skipped"
    elif values["did_plan"] == "modified":
        compliance = "substituted"
    elif values["did_plan"] == "yes":
        compliance = existing.get("compliance") or "match"
    store.upsert_feedback(
        day,
        planned_type=existing.get("planned_type"),
        actual_type=existing.get("actual_type"),
        compliance=compliance,
        feeling=values["feeling"] if values["feeling"] != "unset" else existing.get("feeling"),
        skip_reason=values["skip_reason"]
        if values["skip_reason"] != "unset"
        else existing.get("skip_reason"),
        source="helper",
    )


def run_once(
    client: HomeAssistantClient,
    settings: Settings,
    store: CoachStore,
    manager: PrefsManager,
    wait_oura: bool,
    *,
    notify: bool = True,
) -> Plan:
    _, snapshot = ingest(client, settings, store, wait_oura)
    reconcile_yesterday(store, snapshot)
    changed, prefs = manager.sync_from_helpers(snapshot.today)
    if store.current_prefs() is None:
        prefs = store.insert_prefs(prefs if changed else Prefs.defaults())
    last_fb = store.get_feedback(snapshot.today - timedelta(days=1)) or {}
    feeling = last_fb.get("feeling")
    calendar, load, paces, finish = rebuild_calendar(store, snapshot, prefs, feeling)
    today_row = None
    if prefs.has_race:
        today_row = next((d for d in calendar if d.day == snapshot.today), None)
    upcoming = upcoming_payload(calendar, snapshot.today)
    phase = today_row.phase if today_row else phase_for(snapshot.today, prefs)
    goal = {
        **prefs.as_dict(),
        "days_to_race": days_to_race(snapshot.today, prefs.race_date),
        "phase": phase,
        **{k: finish.get(k) for k in ("p10", "p50", "p90", "p_hit", "feasible")},
    }
    plan = plan_day(
        snapshot,
        settings,
        prefs=prefs,
        calendar_today=today_row,
        upcoming=upcoming,
        prediction=finish,
        goal=goal,
        paces=paces,
    )
    publish_plan(client, plan)
    publish_goal(client, prefs, snapshot.today, load, finish, phase)
    publish_feedback_sensor(client, store.get_feedback(snapshot.today - timedelta(days=1)))
    extra = {
        "oura_readiness": snapshot.recovery.oura_readiness,
        "oura_sleep": snapshot.recovery.oura_sleep,
        "reasons": snapshot.recovery.reasons,
        "prefs": prefs.as_dict(),
        "prediction": {k: finish.get(k) for k in ("p10", "p50", "p90", "p_hit", "feasible")},
        "phase": phase,
        "upcoming": upcoming,
    }
    try:
        store.upsert_recovery(
            snapshot.today,
            snapshot.recovery,
            oura_synced_today=snapshot.oura_synced_today,
            already_trained_today=snapshot.already_trained_today,
        )
        store.upsert_decision(snapshot.today, plan, settings, snapshot.sessions, extra)
    except Exception as exc:  # noqa: BLE001
        log(f"Could not persist coaching facts: {exc}")
    if notify:
        notify_plan(client, settings, plan)
    log(f"Plan: {plan.session_type} ({plan.recovery_band}) — {plan.why}")
    return plan


def run_evening(
    client: HomeAssistantClient,
    settings: Settings,
    store: CoachStore,
    manager: PrefsManager,
) -> None:
    _, snapshot = ingest(client, settings, store, wait_oura=False)
    decision = store.get_decision(snapshot.today)
    if not decision:
        log("No morning plan today; skipping evening check-in")
        return
    manager.reset_feedback_helpers()
    planned_type = decision["session_type"] if decision else None
    planned_title = decision["title"] if decision else "No morning plan"
    actual = primary_actual(snapshot.sessions, snapshot.today)
    compliance = classify_compliance(planned_type, actual)
    recovery_band = decision["recovery_band"] if decision else snapshot.recovery.band
    tomorrow = describe_next_session(
        resolve_tomorrow_row(
            snapshot.today,
            plan_row=store.get_plan_day(snapshot.today + timedelta(days=1)),
            upcoming=(decision.get("extra") or {}).get("upcoming") or [],
        )
    )
    note = coaching_note(compliance, planned_type, actual, tomorrow=tomorrow)
    row = store.upsert_feedback(
        snapshot.today,
        planned_type=planned_type,
        actual_type=actual,
        compliance=compliance,
        recovery_band=recovery_band,
        source="evening",
        notes=note,
    )
    ask_helpers = not settings.mobile_enabled
    message = recap_text(
        planned_title,
        planned_type,
        actual,
        compliance,
        ask_helpers=ask_helpers,
        tomorrow=tomorrow,
    )
    notify_message(client, settings, "Training coach evening", message, android=False, telegram=True)
    if settings.mobile_enabled:
        packs = android_actions(snapshot.today, compliance)
        for i, pack in enumerate(packs):
            body = message
            if i > 0:
                body = (
                    "How did that feel?"
                    if "feel" in pack["tag"]
                    else "Did you follow the plan?"
                )
            notify_message(
                client,
                settings,
                "Training coach evening",
                body,
                android_data={"tag": pack["tag"], "actions": pack["actions"], "sticky": True},
                telegram=False,
                android=True,
            )
    publish_feedback_sensor(client, row)
    log(f"Evening check-in: {compliance} planned={planned_type} actual={actual}")


def apply_checkin(store: CoachStore, manager: PrefsManager, payload: dict, today: date) -> None:
    day_raw = payload.get("day")
    day = date.fromisoformat(str(day_raw)) if day_raw else today
    store.upsert_feedback(
        day,
        feeling=payload.get("feeling"),
        skip_reason=payload.get("skip_reason"),
        compliance=(
            "skipped"
            if payload.get("did_plan") == "skipped"
            else "substituted"
            if payload.get("did_plan") == "modified"
            else payload.get("compliance")
        ),
        source="stdin",
        notes=payload.get("notes"),
    )
    if payload.get("feeling"):
        manager.set_select("input_select.training_coach_feeling", payload["feeling"])
    if payload.get("did_plan"):
        manager.set_select("input_select.training_coach_did_plan", payload["did_plan"])
    if payload.get("skip_reason"):
        manager.set_select("input_select.training_coach_skip_reason", payload["skip_reason"])


def stdin_loop(
    wipe_requested: threading.Event,
    command_queue: list,
    lock: threading.Lock,
) -> None:
    while True:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        except (ValueError, OSError):
            time.sleep(1.0)
            continue
        if not ready:
            continue
        line = sys.stdin.readline()
        if line == "":
            time.sleep(1.0)
            continue
        cmd = line.strip()
        if not cmd:
            continue
        lower = cmd.lower()
        if lower == "wipe_db":
            log("Received wipe_db via stdin; scheduling DuckDB wipe")
            wipe_requested.set()
            continue
        try:
            if cmd.startswith("{") or cmd.startswith("["):
                payload = json.loads(cmd)
            elif lower.startswith("set_prefs"):
                raw = cmd.split(" ", 1)[1] if " " in cmd else "{}"
                payload = {"cmd": "set_prefs", **json.loads(raw)}
            elif lower.startswith("checkin"):
                raw = cmd.split(" ", 1)[1] if " " in cmd else "{}"
                payload = {"cmd": "checkin", **json.loads(raw)}
            else:
                log(f"Unknown stdin command: {cmd!r} (supported: wipe_db, set_prefs, checkin)")
                continue
        except json.JSONDecodeError as exc:
            log(f"Invalid stdin JSON: {exc}")
            continue
        if "cmd" not in payload:
            if "feeling" in payload or "did_plan" in payload:
                payload["cmd"] = "checkin"
            else:
                payload["cmd"] = "set_prefs"
        with lock:
            command_queue.append(payload)


def handle_mobile_action(
    data: dict[str, Any],
    store: CoachStore,
    manager: PrefsManager,
    client: HomeAssistantClient,
    settings: Settings,
) -> None:
    action = str(data.get("action") or "")
    parsed = parse_coach_action(action, data.get("reply_text"))
    if not parsed:
        return
    day = parse_action_day(str(parsed.get("day") or ""))
    if day is None:
        return
    if parsed.get("helper") and parsed.get("option"):
        manager.set_select(parsed["helper"], parsed["option"])
    fields: dict[str, Any] = {"source": "android"}
    if parsed.get("field") == "feeling":
        fields["feeling"] = parsed["option"]
    elif parsed.get("field") == "did_plan":
        option = parsed["option"]
        if option == "skipped":
            fields["compliance"] = "skipped"
        elif option == "modified":
            fields["compliance"] = "substituted"
        elif option == "yes":
            fields["compliance"] = "match"
    elif parsed.get("field") == "skip_reason":
        fields["skip_reason"] = parsed["option"]
        if parsed.get("notes"):
            fields["notes"] = parsed["notes"]
    store.upsert_feedback(day, **fields)
    publish_feedback_sensor(client, store.get_feedback(day))
    for item in android_followups(parsed, day):
        notify_message(
            client,
            settings,
            "Training coach evening",
            item["message"],
            android_data=item["android_data"],
            telegram=False,
            android=True,
        )
    log(f"Android action {action} stored for {day}")


def main() -> None:
    settings = Settings.from_env()
    log(
        f"timezone={settings.timezone} run_time={settings.run_time} "
        f"evening={settings.evening_time} db={settings.db_path}"
    )
    client = HomeAssistantClient()
    store = CoachStore(settings.db_path)
    manager = PrefsManager(client, store)
    try:
        manager.ensure_helpers()
        manager.sync_from_helpers(datetime.now(settings.tz).date())
    except Exception as exc:  # noqa: BLE001
        log(f"Helper setup failed: {exc}")
        if store.current_prefs() is None:
            store.insert_prefs(Prefs.defaults())

    wipe_requested = threading.Event()
    command_queue: list = []
    queue_lock = threading.Lock()
    threading.Thread(
        target=stdin_loop, args=(wipe_requested, command_queue, queue_lock), daemon=True
    ).start()

    stop_ws = threading.Event()
    if settings.mobile_enabled:
        token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN") or ""
        threading.Thread(
            target=run_action_listener,
            args=(
                settings,
                token,
                client.base_url,
                lambda data: handle_mobile_action(data, store, manager, client, settings),
                stop_ws,
            ),
            daemon=True,
        ).start()
        log(f"Android notify {settings.mobile_notify_service} (ws {websocket_url(client.base_url)})")

    ran_startup = False
    last_fired: tuple[date, str] | None = None
    last_poll = 0.0
    pending_prefs_at: float | None = None
    last_fingerprint = (store.current_prefs() or Prefs.defaults()).fingerprint

    while True:
        now = datetime.now(settings.tz)
        if wipe_requested.is_set():
            wipe_requested.clear()
            log("Wiping local DuckDB")
            try:
                store.wipe()
                store.insert_prefs(Prefs.defaults())
                log("DuckDB wiped; re-seeding and planning")
            except Exception as exc:  # noqa: BLE001
                log(f"Wipe failed: {exc}")
            else:
                run_once(client, settings, store, manager, wait_oura=False)
                continue

        with queue_lock:
            commands = list(command_queue)
            command_queue.clear()
        for payload in commands:
            cmd = payload.get("cmd")
            try:
                if cmd == "set_prefs":
                    manager.apply_stdin(payload, now.date())
                    run_once(client, settings, store, manager, wait_oura=False, notify=False)
                elif cmd == "checkin":
                    apply_checkin(store, manager, payload, now.date())
                    publish_feedback_sensor(client, store.get_feedback(now.date()))
            except Exception as exc:  # noqa: BLE001
                log(f"stdin {cmd} failed: {exc}")

        if time.monotonic() - last_poll >= max(30, settings.poll_seconds):
            last_poll = time.monotonic()
            try:
                changed, prefs = manager.sync_from_helpers(now.date())
                capture_feedback_helpers(store, manager, now.date())
                if changed and prefs.fingerprint != last_fingerprint:
                    pending_prefs_at = time.monotonic()
                    last_fingerprint = prefs.fingerprint
            except Exception as exc:  # noqa: BLE001
                log(f"Helper poll failed: {exc}")

        if pending_prefs_at is not None and time.monotonic() - pending_prefs_at >= 30:
            pending_prefs_at = None
            log("Prefs changed; rebuilding plan")
            try:
                run_once(client, settings, store, manager, wait_oura=False, notify=False)
            except Exception as exc:  # noqa: BLE001
                log(f"Prefs replan failed: {exc}")

        if settings.run_immediately and not ran_startup:
            log("Running immediately on start")
            now = datetime.now(settings.tz)
            notify = False
            if morning_slot_passed(now, settings):
                notify = consume_daily_notify(store, now.date(), "morning")
                if notify:
                    log("Morning slot already passed; notifying startup plan")
                else:
                    log("Morning already notified today; publishing without notify")
            else:
                log("Morning still ahead; publishing without notify")
            run_once(client, settings, store, manager, wait_oura=False, notify=notify)
            ran_startup = True

        target, kind = next_named_event(datetime.now(settings.tz), settings)
        sleep_s = max(1.0, (target - datetime.now(settings.tz)).total_seconds())
        log(f"Sleeping {int(sleep_s)}s until {kind} at {target.strftime('%H:%M')}")
        deadline = time.monotonic() + min(sleep_s, 30.0)
        while time.monotonic() < deadline:
            if wipe_requested.is_set():
                break
            with queue_lock:
                if command_queue:
                    break
            time.sleep(min(5.0, max(0.1, deadline - time.monotonic())))
        else:
            now = datetime.now(settings.tz)
            if should_fire_named_event(now, target, kind, last_fired):
                last_fired = (now.date(), kind)
                if kind == "morning":
                    if consume_daily_notify(store, now.date(), "morning"):
                        run_once(client, settings, store, manager, wait_oura=True)
                    else:
                        log("Skipping duplicate morning notify")
                    time.sleep(60)
                elif kind == "evening":
                    if consume_daily_notify(store, now.date(), "evening"):
                        run_evening(client, settings, store, manager)
                    else:
                        log("Skipping duplicate evening notify")
                    time.sleep(60)
            continue


if __name__ == "__main__":
    main()
