"""Evening check-in: planned vs actual, Android actions, helper copy."""

from __future__ import annotations

from datetime import date

from classify import QUALITY, REST, Session
from entities import DID_PLAN_HELPER, FEELING_HELPER, SKIP_REASON_HELPER
from goal import DID_PLAN_OPTIONS, FEELING_OPTIONS, SKIP_REASON_OPTIONS

COMPLIANCE_MATCH = "match"
COMPLIANCE_FAMILY = "same_family"
COMPLIANCE_SUBSTITUTED = "substituted"
COMPLIANCE_SKIPPED = "skipped"
COMPLIANCE_EXTRA = "extra"


def primary_actual(sessions: list[Session], day: date) -> str | None:
    today = [s for s in sessions if s.when == day]
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


def coaching_note(compliance: str, planned: str | None, actual: str | None) -> str:
    if compliance == COMPLIANCE_MATCH:
        return "Nice — that matches the morning plan. Easy tomorrow unless the calendar says otherwise."
    if compliance == COMPLIANCE_FAMILY:
        return "Quality work is in; intervals vs tempo is close enough. Keep the next hard session honest."
    if compliance == COMPLIANCE_SKIPPED:
        if planned in QUALITY:
            return "Quality was skipped. Don’t cram it tomorrow; the next good-recovery day can pick it up."
        if planned == "long_run":
            return "Long run is still the weekend priority; midweek stays easy."
        return "Missed session noted. One skip is fine — don’t stack extra tomorrow."
    if compliance == COMPLIANCE_SUBSTITUTED:
        return f"You did {actual or 'something else'} instead of {planned}. The week still counts; next hard day waits 48h."
    return "Extra session on a rest day — treat tomorrow as easier if legs feel it."


def recap_text(
    planned_title: str,
    planned_type: str | None,
    actual: str | None,
    compliance: str,
    *,
    ask_helpers: bool,
) -> str:
    actual_label = actual.replace("_", " ") if actual else "nothing logged"
    planned_label = planned_type.replace("_", " ") if planned_type else "rest"
    lines = [
        f"This morning: {planned_title}",
        f"Logged: {actual_label} (planned {planned_label} → {compliance}).",
        coaching_note(compliance, planned_type, actual),
    ]
    if ask_helpers:
        lines.append(
            "Please set how it felt in HA: "
            f"{FEELING_HELPER}, {DID_PLAN_HELPER}"
            + (f", {SKIP_REASON_HELPER}" if compliance != COMPLIANCE_MATCH else "")
            + "."
        )
    return "\n".join(lines)


def android_actions(day: date, compliance: str) -> list[dict]:
    key = day.isoformat()
    notices: list[dict] = []
    if compliance != COMPLIANCE_MATCH:
        notices.append(
            {
                "tag": "training_coach_checkin_comp",
                "actions": [
                    {"action": f"coach_{key}_comp_did", "title": "Did it"},
                    {"action": f"coach_{key}_comp_skipped", "title": "Skipped"},
                    {"action": f"coach_{key}_comp_changed", "title": "Changed"},
                ],
            }
        )
    notices.append(
        {
            "tag": "training_coach_checkin_feel",
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
        "tag": "training_coach_checkin_skip",
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
