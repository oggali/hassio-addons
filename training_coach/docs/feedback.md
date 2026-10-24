# Evening feedback

[Back to the add-on README](../README.md)

Evening compares the morning plan with every training session logged today, stores a row, and sends Telegram. It does not pick tomorrow’s session. Recovery is not known yet. The categories below are the ones later planning actually reads.

Code: [`feedback.py`](../app/feedback.py), option lists in [`goal.py`](../app/goal.py#L24-L27), storage in [`feedback_history`](../app/store.py#L154-L166). The evening call is [`run_evening`](../app/main.py#L662-L747).

## Two different answers

| Field | Who sets it | Values |
|---|---|---|
| `compliance` | The add-on, from logged sessions | `match`, `same_family`, `substituted`, `skipped`, `extra` |
| `did_plan` | You, helper or button | `unset`, `yes`, `modified`, `skipped` |
| `feeling` | You | `unset`, `great`, `ok`, `tired`, `wiped` |
| `skip_reason` | You | `unset`, `no_time`, `tired`, `sore`, `weather`, `other_sport` |
| `effort_fit` | You, after a session that was done | `unset`, `too_easy`, `about_right`, `too_hard` |

Evening writes `compliance` from the log. A button or a `checkin` can replace that value afterwards:

- Android **Did it** stores `match`. **Changed** stores `substituted`. **Skipped** stores `skipped` ([`handle_mobile_action`](../app/main.py#L833-L840)).
- Stdin `did_plan` `skipped` stores `skipped`, and `modified` stores `substituted`. `yes` leaves the evening compliance in place ([`apply_checkin`](../app/main.py#L758-L764)).

Feeling, skip reason, and effort fit do not change `compliance`. The ladder and the Monte Carlo search read the stored compliance, so a tap is what they see later.

Setting the helpers by hand is copied into today’s row on the helper poll ([`capture_feedback_helpers`](../app/main.py#L563-L591)). `did_plan` `skipped` and `modified` overwrite compliance the same way as the buttons. `yes` keeps the evening compliance, or stores `match` when that row had none.

A late run after evening can upgrade yesterday’s `skipped` row the next morning when a session has shown up ([`reconcile_yesterday`](../app/main.py#L543-L561)).

## Compliance

[`classify_compliance`](../app/feedback.py#L113-L131), using every training session today, not only the hardest:

| Planned | Logged | Compliance |
|---|---|---|
| `rest` | nothing | `match` |
| `rest` | any training | `extra` |
| anything else | nothing | `skipped` |
| a type that appears in today’s log | that type is among them | `match` |
| `intervals` or `tempo` | the other quality type, not the planned one | `same_family` |
| anything else that does not match | some other training | `substituted` |

`match`, `same_family`, and `substituted` count as “did the session” ([`DID_SESSION_COMPLIANCE`](../app/feedback.py#L31-L33)). Those are the rows that ask for effort fit.

Which session is named first: quality, then any non-rest type, then longer duration ([`logged_sessions`](../app/feedback.py#L78-L89)). Extra types that are not the planned one are listed in the coaching line ([`coaching_note`](../app/feedback.py#L198-L247)).

Copy, in short:

- `match` — matches the morning plan.
- `same_family` — quality is in; intervals vs tempo is close enough.
- `skipped` quality — do not cram it tomorrow.
- `skipped` long run — still the weekend priority.
- other `skipped` — one skip is fine.
- `substituted` — the week still counts; next hard day waits 48h.
- `extra` — extra work on a rest day; go easier if the legs feel it.

If today already has a hard-or-long session and tomorrow’s calendar row is also hard-or-long, the evening line says morning will switch it. It does not choose easy vs rest ([`describe_evening_tomorrow`](../app/feedback.py#L154-L177)). Hard-or-long is defined in [Session categories](sessions.md).

## Buttons vs helpers

Android allows three actions. The phone therefore does not show every helper option.

First cards, from [`android_actions`](../app/feedback.py#L443-L467):

- Compliance is not `match`: **Did it** / **Skipped** / **Changed** → `did_plan` `yes` / `skipped` / `modified`.
- Always: **Great** / **OK** / **Tired**. `wiped` exists on the helper and is not a button.

Follow-ups, from [`android_followups`](../app/feedback.py#L402-L440):

- **Skipped** opens **No time** / **Sore** / **Reply**. Reply is a text box stored as `other_sport` plus the text in `notes`. Helper-only skip reasons are `tired` and `weather`.
- **Did it** or **Changed** opens **Too easy** / **Right** / **Too hard**.
- A feeling tap does the same effort card when compliance is already in “did the session”.
- Any other tap replaces the card with `Logged: …` and dismisses it after 8 seconds.

Action names look like `coach_2026-10-24_feel_great`. [`parse_coach_action`](../app/feedback.py#L486-L525) maps them onto the helper entity and rejects unknown options.

Telegram always gets the recap. It names the helpers only when Android is off ([`recap_text`](../app/feedback.py#L305-L353)). With Android on, Telegram does not ask you to type the answers. The recap, including today’s load and the 7-day sum, is in [Notifications](notifications.md).

Stdin `checkin` writes the same fields. Examples are in the [README](../README.md#live-prefs-helpers).

## What the next plan reads

Evening stores `planned_type`, `actual_type` (comma-separated when there are several), `compliance`, `recovery_band`, and the coaching note. Feeling, skip reason, and effort fit arrive later, when you tap or set the helper, and update that day’s row.

Those values change the calendar, not the recovery band. The ladder uses **yesterday’s** feeling, and the compliance stored on the most recent quality day (a Did it / Changed / Skipped tap may already have replaced the automatic one). See [How a day is chosen](planning.md#quality-ladders).

The search over the last 120 days of `feedback_history`:

- For a planned type with at least two rows, the skip chance is the fraction whose compliance is `skipped`. Fewer than two rows uses **12%**.
- `skip_reason` `no_time` records that weekday. A long run placed on that weekday is penalized when the day is Monday–Friday.
- `skip_reason` `sore` asks for a wider gap before the next hard day. Feeling `sore` is also checked, but it is not a feeling-helper option.
- Feeling `tired`, `wiped`, or `sore` on a hard plan that was published with recovery `good` raises the chance a hard day scores as too much: one such row adds 0.10, two or more add 0.25, on top of a 0.15 base.

Day activity on the evening message (steps, calories, intensity minutes) is context. It is not a compliance input.
