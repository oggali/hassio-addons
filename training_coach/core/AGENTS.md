# Core

Decision rules for the running coach. No HTTP, no accounts, and no vendor clients. The API, and later the Home Assistant add-on, call `plan_from_payload` and `evening_from_payload` in `engine.py`.

The add-on still has its own copy of these modules. This package is the one the API imports. Change a rule here and on the `docs/` page that owns it. The thresholds in those pages are the ones this package implements.

## Layout

| Module | Owns |
|---|---|
| `engine.py` | `plan_from_payload`, `evening_from_payload`. The only entry points. |
| `inputs.py` | Dict payloads in and out: prefs, locks, sessions, recovery signals, day activity. |
| `classify.py` | Session types. Strava and Garmin rows become `Session`. Same-outing merge. |
| `splits.py` | Kilometre splits and laps reclassify a matched run. The match copies laps onto the session. |
| `features.py` | Recovery band, fused day activity, `FeatureSnapshot`. Home Assistant entity collection lives in this file. |
| `entities.py` | Home Assistant sensor ids. The API does not call it. Kept so the add-on can switch to this package. |
| `load.py` | Session load, CTL / ATL / TSB, running volume, long-run floor. |
| `paces.py` | Easy pace, Riegel `k`, predicted finish. |
| `periodize.py` | Remaining-day skeleton, interval and tempo ladders, km and pace ranges. |
| `simulate.py` | Finish-time Monte Carlo and the small search over remaining days. Stdlib `random` only. |
| `planner.py` | Today's session. Recovery overrides the calendar, locks, and weekly quotas. |
| `recipes.py` | Title, km range, pace, interval structure. |
| `feedback.py` | Evening recap, compliance, what the next plan reads. |
| `goal.py` | `Prefs`, race distances, target time, phase. |
| `messages.py` | Morning message text. |
| `settings.py` | Ops knobs (`timezone`, max heart rate, long-run minutes). |
| `parse.py` | Numbers, durations, datetimes, unavailable states. |
| `tests/` | `unittest`. No network. |

## Docs

| Page | Owns |
|---|---|
| `docs/sessions.md` | Session types, sport routing, heart-rate reference, Strava/Garmin merge. |
| `docs/recovery.md` | `poor` / `ok` / `good`. |
| `docs/planning.md` | Quotas, race skeleton, phases, ladders, paces, Monte Carlo search. |
| `docs/load.md` | Intensity, CTL / ATL / TSB, running volume, long-run floor. |
| `docs/feedback.md` | Compliance and what the next plan reads. |
| `docs/notifications.md` | Morning and evening words. |

## Rules that are easy to break

- Quality is `intervals` and `tempo` only. `long_run` is taxing and is not quality.
- Recovery wins over the calendar, locks, and weekly quotas. Change `pick_session_type` and `overlay_calendar` together when the gate is shared.
- A published intervals, tempo, or long run clears an unlocked hard or long day tomorrow (`ease_stacked_tomorrow`) before the upcoming list is built. A lock and race day stay.
- Strava is kept when it and Garmin describe the same outing.
- A Garmin document counts only when its `calendarDate` is today. Yesterday's sleep must not vote.
- An Oura document counts only when its `day` is today.
- Oura activity times arrive as seconds. Store them as minutes. The API does that before this package sees them.
- Oura workouts are not an input. Sport sessions come from Strava and Garmin.
- Ride and ski kilometres are not running volume and not race-prediction inputs.
- Weekday locks are placed before the week template and count toward the weekly caps. Search does not drop, shrink, or swap a locked row.
- Tune a threshold in the module that owns the constant. Those are code constants.

## Tests

From the repo root:

```bash
just test
```

| File | Covers |
|---|---|
| `tests/test_planner.py` | Classify, recovery, quotas, Strava/Garmin fixtures. |
| `tests/test_race_plan.py` | Paces, periodize, Monte Carlo, calendar overlay. |
| `tests/test_splits.py` | Split classification. |
| `tests/test_engine.py` | `plan_from_payload` and `evening_from_payload`. |
