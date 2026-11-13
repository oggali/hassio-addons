"""Morning and evening copy. Delivery (push, Telegram, the screen) stays outside."""

from __future__ import annotations

from coach.feedback import format_load_line
from coach.planner import Plan


def format_morning_message(plan: Plan, weekly_load: float | None = None) -> str:
    upcoming = ""
    if plan.upcoming:
        upcoming = "\n\nUpcoming:\n" + "\n".join(
            item.get("line", "") for item in plan.upcoming[:7]
        )
    load_line = format_load_line(weekly=weekly_load)
    load_bit = f"\n{load_line}" if load_line else ""
    return (
        f"Today: {plan.recipe.title}\n"
        f"{plan.recipe.details}\n\n"
        f"Why: {plan.why}\n"
        f"Recovery: {plan.recovery_band}"
        f"{load_bit}"
        f"{upcoming}"
    )
