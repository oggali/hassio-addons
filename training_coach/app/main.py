"""Morning training coach loop."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Allow `python3 /app/main.py` and `python3 main.py` from this folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from entities import SESSION_SENSOR, SUMMARY_SENSOR, tracked_entity_ids
from features import build_snapshot
from ha_client import HomeAssistantClient
from persist import append_decision
from planner import Plan, plan_day
from settings import Settings


def log(message: str) -> None:
    print(f"[training_coach] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.strip().split(":")
    return int(hour), int(minute)


def seconds_until_run(now: datetime, run_time: str) -> float:
    hour, minute = parse_hhmm(run_time)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


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


def history_fallback(client: HomeAssistantClient, settings: Settings):
    start = datetime.now(settings.tz) - timedelta(days=28)
    entity_ids = [
        f"{settings.strava_entity_prefix}_run_date",
        f"{settings.strava_entity_prefix}_weight_training_date",
    ]
    try:
        return client.get_history(entity_ids, start)
    except Exception as exc:  # noqa: BLE001
        log(f"History fetch failed: {exc}")
        return None


def publish_plan(client: HomeAssistantClient, plan: Plan) -> None:
    attributes = {
        "friendly_name": "Training coach session",
        "icon": "mdi:run-fast" if plan.session_type != "rest" else "mdi:bed",
        "title": plan.recipe.title,
        "details": plan.recipe.details,
        "duration_min": plan.recipe.duration_min,
        "why": plan.why,
        "recovery_band": plan.recovery_band,
        "yesterday": plan.yesterday,
        "week_counts": plan.week_counts,
        "oura_synced_today": plan.oura_synced_today,
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
        },
    )


def notify_plan(client: HomeAssistantClient, settings: Settings, plan: Plan) -> None:
    domain, service = settings.notify_domain_service
    message = (
        f"Today: {plan.recipe.title}\n"
        f"{plan.recipe.details}\n\n"
        f"Why: {plan.why}\n"
        f"Recovery: {plan.recovery_band}"
    )
    try:
        client.call_service(domain, service, {"message": message, "title": "Training coach"})
        log(f"Notified via {domain}.{service}")
    except Exception as exc:  # noqa: BLE001
        log(f"Notify failed: {exc}")


def run_once(client: HomeAssistantClient, settings: Settings, wait_oura: bool) -> Plan:
    if wait_oura:
        states = wait_for_oura(client, settings)
    else:
        states = client.get_states(tracked_entity_ids(settings.strava_entity_prefix))
    history = history_fallback(client, settings)
    snapshot = build_snapshot(states, settings, history=history)
    plan = plan_day(snapshot, settings)
    publish_plan(client, plan)
    notify_plan(client, settings, plan)
    extra = {
        "oura_readiness": snapshot.recovery.oura_readiness,
        "oura_sleep": snapshot.recovery.oura_sleep,
        "reasons": snapshot.recovery.reasons,
        "session_titles": [s.title for s in snapshot.sessions[:10]],
    }
    try:
        append_decision(settings.decisions_path, plan, extra)
    except Exception as exc:  # noqa: BLE001
        log(f"Could not persist decision: {exc}")
    log(f"Plan: {plan.session_type} ({plan.recovery_band}) — {plan.why}")
    return plan


def main() -> None:
    settings = Settings.from_env()
    log(f"timezone={settings.timezone} run_time={settings.run_time}")
    client = HomeAssistantClient()
    ran_startup = False
    while True:
        now = datetime.now(settings.tz)
        if settings.run_immediately and not ran_startup:
            log("Running immediately on start")
            run_once(client, settings, wait_oura=False)
            ran_startup = True
        sleep_s = seconds_until_run(now, settings.run_time)
        log(f"Sleeping {int(sleep_s)}s until {settings.run_time}")
        time.sleep(sleep_s)
        run_once(client, settings, wait_oura=True)
        # Avoid a double-run if the job finishes before the clock leaves run_time.
        time.sleep(60)


if __name__ == "__main__":
    main()
