"""Evening check-in: planned vs actual, Android actions, helper copy."""

from __future__ import annotations

from datetime import date, timedelta

from classify import QUALITY, REST, Session, is_training_session, session_day
from entities import DID_PLAN_HELPER, FEELING_HELPER, SKIP_REASON_HELPER
from goal import DID_PLAN_OPTIONS, FEELING_OPTIONS, SKIP_REASON_OPTIONS
from paces import format_pace_range
from planner import TITLES
from recipes import format_km_range

COMPLIANCE_MATCH = "match"
COMPLIANCE_FAMILY = "same_family"
COMPLIANCE_SUBSTITUTED = "substituted"
COMPLIANCE_SKIPPED = "skipped"
COMPLIANCE_EXTRA = "extra"

TAG_CHECKIN_COMP = "training_coach_checkin_comp"
TAG_CHECKIN_FEEL = "training_coach_checkin_feel"
TAG_CHECKIN_SKIP = "training_coach_checkin_skip"
ACK_TIMEOUT_SECONDS = 8
ACK_LABELS = {
    ("comp", "yes"): "Did it",
    ("comp", "skipped"): "Skipped",
    ("comp", "modified"): "Changed",
    ("feel", "great"): "Great",
    ("feel", "ok"): "OK",
    ("feel", "tired"): "Tired",
    ("feel", "wiped"): "Wiped",
    ("skip", "no_time"): "No time",
    ("skip", "tired"): "Tired",
    ("skip", "sore"): "Sore",
    ("skip", "weather"): "Weather",
    ("skip", "other_sport"): "Other",
}


def primary_actual(sessions: list[Session], day: date) -> str | None:
    today = [s for s in sessions if session_day(s) == day and is_training_session(s)]
    if not today:
        return None
    ranked = sorted(
        today,
        key=lambda s: (
            0 if s.session_type in QUALITY else 1 if s.session_type != REST else 2,
            -(s.duration_min or 0),
        ),
    )
    return ranked[0].session_type


def classify_compliance(planned: str | None, actual: str | None) -> str:
    planned = planned or REST
    if planned == REST:
        return COMPLIANCE_MATCH if actual is None else COMPLIANCE_EXTRA
    if actual is None:
        return COMPLIANCE_SKIPPED
    if actual == planned:
        return COMPLIANCE_MATCH
    if planned in QUALITY and actual in QUALITY:
        return COMPLIANCE_FAMILY
    return COMPLIANCE_SUBSTITUTED


def describe_next_session(row: dict | None) -> str | None:
    """Human label for a plan_days / upcoming row, e.g. 'gym / strength'."""
    if not row:
        return None
    session_type = row.get("session") or row.get("session_type")
    if not session_type:
        return None
    title = TITLES.get(session_type, str(session_type).replace("_", " ")).lower()
    km = row.get("km") or format_km_range(row.get("km_min"), row.get("km_max"))
    pace = row.get("pace")
    if not pace:
        pace = format_pace_range(row.get("pace_min"), row.get("pace_max"))
    parts = [title]
    if km:
        parts.append(str(km))
    if pace:
        parts.append(f"@ {pace}")
    return " ".join(parts)


def resolve_tomorrow_row(
    today: date,
    *,
    plan_row: dict | None = None,
    upcoming: list[dict] | None = None,
) -> dict | None:
    if plan_row:
        return plan_row
    target = (today + timedelta(days=1)).isoformat()
    for item in upcoming or []:
        day = item.get("day")
        if hasattr(day, "isoformat"):
            day = day.isoformat()
        if day == target:
            return item
    return None


def coaching_note(
    compliance: str,
    planned: str | None,
    actual: str | None,
    tomorrow: str | None = None,
) -> str:
    next_line = f" Tomorrow: {tomorrow}." if tomorrow else ""
    if compliance == COMPLIANCE_MATCH:
        if tomorrow:
            return f"Nice — that matches the morning plan.{next_line}"
        return "Nice — that matches the morning plan."
    if compliance == COMPLIANCE_FAMILY:
        if tomorrow:
            return f"Quality work is in; intervals vs tempo is close enough.{next_line}"
        return "Quality work is in; intervals vs tempo is close enough. Keep the next hard session honest."
    if compliance == COMPLIANCE_SKIPPED:
        if planned in QUALITY:
            return (
                "Quality was skipped. Don’t cram it tomorrow; the next good-recovery day "
                f"can pick it up.{next_line}"
            )
        if planned == "long_run":
            if tomorrow:
                return f"Long run is still the weekend priority.{next_line}"
            return "Long run is still the weekend priority; midweek stays easy."
        if tomorrow:
            return f"Missed session noted. One skip is fine — don’t stack extra.{next_line}"
        return "Missed session noted. One skip is fine — don’t stack extra tomorrow."
    if compliance == COMPLIANCE_SUBSTITUTED:
        return (
            f"You did {actual or 'something else'} instead of {planned}. "
            f"The week still counts; next hard day waits 48h.{next_line}"
        )
    if tomorrow:
        return f"Extra session on a rest day — go easier if legs feel it.{next_line}"
    return "Extra session on a rest day — treat tomorrow as easier if legs feel it."


def recap_text(
    planned_title: str,
    planned_type: str | None,
    actual: str | None,
    compliance: str,
    *,
    ask_helpers: bool,
    tomorrow: str | None = None,
) -> str:
    actual_label = actual.replace("_", " ") if actual else "nothing logged"
    planned_label = planned_type.replace("_", " ") if planned_type else "rest"
    lines = [
        f"This morning: {planned_title}",
        f"Logged: {actual_label} (planned {planned_label} → {compliance}).",
        coaching_note(compliance, planned_type, actual, tomorrow=tomorrow),
    ]
    if ask_helpers:
        lines.append(
            "Please set how it felt in HA: "
            f"{FEELING_HELPER}, {DID_PLAN_HELPER}"
            + (f", {SKIP_REASON_HELPER}" if compliance != COMPLIANCE_MATCH else "")
            + "."
        )
    return "\n".join(lines)


def checkin_tag(kind: str) -> str | None:
    return {
        "comp": TAG_CHECKIN_COMP,
        "feel": TAG_CHECKIN_FEEL,
        "skip": TAG_CHECKIN_SKIP,
    }.get(kind)


def action_ack_message(parsed: dict) -> str:
    notes = str(parsed.get("notes") or "").strip()
    if notes:
        if len(notes) > 80:
            notes = notes[:77] + "..."
        return f"Logged: {notes}"
    label = ACK_LABELS.get((parsed.get("kind"), parsed.get("option")))
    return f"Logged: {label}" if label else "Logged"


def android_followups(parsed: dict, day: date) -> list[dict]:
    """Companion payloads after a button tap (same tag replaces the sticky card)."""
    tag = checkin_tag(str(parsed.get("kind") or ""))
    if not tag:
        return []
    if parsed.get("kind") == "comp" and parsed.get("option") == "skipped":
        pack = skip_reason_actions(day)
        return [
            {"message": "clear_notification", "android_data": {"tag": tag}},
            {
                "message": "Why did you skip?",
                "android_data": {
                    "tag": pack["tag"],
                    "actions": pack["actions"],
                    "sticky": True,
                },
            },
        ]
    return [
        {
            "message": action_ack_message(parsed),
            "android_data": {
                "tag": tag,
                "timeout": ACK_TIMEOUT_SECONDS,
                "sticky": False,
            },
        }
    ]


def android_actions(day: date, compliance: str) -> list[dict]:
    key = day.isoformat()
    notices: list[dict] = []
    if compliance != COMPLIANCE_MATCH:
        notices.append(
            {
                "tag": TAG_CHECKIN_COMP,
                "actions": [
                    {"action": f"coach_{key}_comp_did", "title": "Did it"},
                    {"action": f"coach_{key}_comp_skipped", "title": "Skipped"},
                    {"action": f"coach_{key}_comp_changed", "title": "Changed"},
                ],
            }
        )
    notices.append(
        {
            "tag": TAG_CHECKIN_FEEL,
            "actions": [
                {"action": f"coach_{key}_feel_great", "title": "Great"},
                {"action": f"coach_{key}_feel_ok", "title": "OK"},
                {"action": f"coach_{key}_feel_tired", "title": "Tired"},
            ],
        }
    )
    return notices


def skip_reason_actions(day: date) -> dict:
    key = day.isoformat()
    return {
        "tag": TAG_CHECKIN_SKIP,
        "actions": [
            {"action": f"coach_{key}_skip_notime", "title": "No time"},
            {"action": f"coach_{key}_skip_sore", "title": "Sore"},
            {
                "action": f"coach_{key}_skip_other",
                "title": "Reply",
                "behavior": "textInput",
            },
        ],
    }


def parse_coach_action(action: str, reply_text: str | None = None) -> dict | None:
    if not action or not action.startswith("coach_"):
        return None
    parts = action.split("_")
    # coach_YYYY-MM-DD_feel_great  → ['coach', 'YYYY-MM-DD', 'feel', 'great']
    if len(parts) < 4:
        return None
    day = parts[1]
    kind = parts[2]
    rest = "_".join(parts[3:])
    out: dict = {"day": day, "kind": kind, "value": rest}
    if kind == "comp":
        mapping = {"did": "yes", "skipped": "skipped", "changed": "modified"}
        out["helper"] = DID_PLAN_HELPER
        out["option"] = mapping.get(rest)
        out["field"] = "did_plan"
    elif kind == "feel":
        option = rest if rest in FEELING_OPTIONS else None
        out["helper"] = FEELING_HELPER
        out["option"] = option
        out["field"] = "feeling"
    elif kind == "skip":
        mapping = {"notime": "no_time", "sore": "sore", "other": "other_sport"}
        out["helper"] = SKIP_REASON_HELPER
        out["option"] = mapping.get(rest)
        out["field"] = "skip_reason"
        if rest == "other" and reply_text:
            out["notes"] = reply_text
            out["option"] = "other_sport"
    else:
        return None
    allowed = DID_PLAN_OPTIONS + FEELING_OPTIONS + SKIP_REASON_OPTIONS
    if out.get("option") not in allowed:
        return None
    return out
