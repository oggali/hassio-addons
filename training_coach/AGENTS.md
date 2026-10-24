# Training Coach

Home Assistant add-on that reads Oura, Garmin, and Strava sensors already in HA, then publishes today's session, a race-goal prediction, and Telegram. Optional Android notifications can repeat the evening message and collect button replies. Physiology and periodization only; not medical advice. User-facing detail is `README.md` — update it when behavior, helpers, sensors, or stdin commands change.

`app/` is a flat script directory, not a package. There is no `__init__.py`. `main.py` and every test insert `app/` on `sys.path` and import modules by filename (`from planner import plan_day`). Keep new modules the same way.

## Layout

| Path | Role |
|---|---|
| `config.yaml` | Add-on manifest. Ops options only (timezone, clocks, notify services, Strava prefix, long-run minutes). Race goal and weekly caps are not options: changing options restarts the container. |
| `build.yaml`, `Dockerfile` | `ghcr.io/hassio-addons/debian-base`, Python 3, `pip install app/requirements.txt` (`requests`, `duckdb`, `websocket-client`). |
| `run.sh` | `bashio` config → environment variables → `python3 /app/main.py`. |
| `app/settings.py` | `Settings.from_env()`. Ops knobs only. |
| `app/entities.py` | HA entity ids: Oura, Garmin, Strava slots, coach sensors, input helpers. |
| `app/parse.py` | Unavailable states, numbers, durations, datetimes. |
| `app/ha_client.py` | Supervisor REST (`SUPERVISOR_TOKEN` or `HA_TOKEN`, default `http://supervisor/core/api`). |
| `app/ha_ws.py` | Short websocket for helper creation, plus the Android action listener. |
| `app/prefs.py` | Create helpers if missing, poll them, append `prefs_history`. |
| `app/goal.py` | `Prefs`, race distances, target-time parse, phase (`base` / `build` / `peak` / `taper` / `race`). |
| `app/classify.py` | Session types and Strava/Garmin → `Session`. Same-outing merge. |
| `app/splits.py` | `sensor.strava_latest_splits` (km splits, laps, relative effort) reclassifies a matched run. |
| `app/features.py` | Recovery band, fused day activity, `FeatureSnapshot`. |
| `app/load.py` | Session load and Banister CTL / ATL / TSB. Running volume only. |
| `app/paces.py` | Easy pace from history, Riegel `k`, predicted finish. |
| `app/periodize.py` | Remaining-day skeleton, interval/tempo ladders, km and pace ranges. |
| `app/simulate.py` | Finish-time Monte Carlo (P10/P50/P90) and a small search over remaining days. |
| `app/planner.py` | Today's session. Recovery overrides the calendar. |
| `app/recipes.py` | Human title, km range, pace, interval structure. |
| `app/feedback.py` | Evening recap, compliance, Android action packs (max three buttons). |
| `app/store.py` | DuckDB schema, upserts, share copy, wipe. `SCHEMA_VERSION` is `"7"`. |
| `app/persist.py` | Empty shim. Call `CoachStore`, not this module. |
| `app/main.py` | Process loop: stdin, morning, evening, share export, helper poll. |
| `tests/` | `unittest`. No Home Assistant. Fixture states in `test_planner.py`. |

## Runtime

`main()` loads settings, opens `/data/coach.duckdb`, ensures helpers, then loops. Three daily slots (`run_time`, `evening_time`, `share_export_time` default `23:00`) fire once per local day. A 30s sleep also drains stdin and polls helpers. Startup runs one plan immediately (`run_immediately_on_start`); it notifies only if the morning slot has already passed and today's morning notify was not sent yet. Notify claims live in DuckDB `meta` (`last_notify_morning`, `last_notify_evening`).

Stdin (`hassio.addon_stdin`): `wipe_db`, `fetch_sessions`, `set_prefs`, `checkin`. JSON objects are accepted; a body with `feeling` or `did_plan` and no `cmd` is a check-in, otherwise `set_prefs`. `wipe_db` deletes the live database and re-seeds history (365 days) on the next plan. `fetch_sessions` upserts current sensors and refreshes the share copy; it does not notify or rebuild the plan.

Telegram (`notify_service`) is always used. Android (`mobile_notify_service`) is optional. Empty, `null`, `none`, `unknown`, or `false` disables it and the websocket listener.

## Morning path

`run_once` in `main.py`:

1. `ingest` reads `tracked_entity_ids`, classifies Strava + Garmin, upserts sessions. Oura workouts are never read. If the store has never been seeded, history is pulled once.
2. `reconcile_yesterday` upgrades a `skipped` row when a late session showed up.
3. Prefs sync from helpers. A fingerprint change rebuilds the plan after ~30s, without a notification.
4. `rebuild_calendar`: load snapshot → paces → `build_skeleton` → `finish_distribution` → `search_calendar` → replace `plan_days`.
5. `plan_day`. With a race and a row for today, `overlay_calendar`. Otherwise `pick_session_type` (weekly quotas, weekend long-run bias).
6. Publish `sensor.training_coach_session`, `_summary`, `_goal`, `_feedback`. Persist recovery and the decision. Optionally notify, then copy the database to share.

## Evening path

`run_evening` needs a morning `decisions` row. It stores end-of-day CTL/ATL/TSB, compares the plan with every training session logged today, writes `feedback_history`, and sends Telegram. It does not choose tomorrow's session: recovery is not known yet. If today was hard/long and tomorrow's calendar is hard/long, the copy says morning will switch it. Android on: buttons write helpers and may open one follow-up card (effort, or skip reason). Android off: the Telegram text names the helpers to set by hand. A late session after evening is fixed next morning.

## Decision rules that are easy to break

Session type constants live in `classify.py`. Use them; do not sprinkle new strings.

- Quality is `intervals` and `tempo` only. `long_run` is taxing but not quality.
- `HARD_OR_LONG` is quality + `long_run` + `cross_hard` + legacy `cross_long`. `cross_easy` and `cross_easy_long` add load and do not consume `HARD_SPACING_HOURS` (48) or block the next day like a long run.
- New classify paths emit `cross_easy_long` for a long easy ride/ski. Keep `cross_long` so old rows still gate recovery.
- Nordic/skate ski minutes are slightly heavier than bike (`SKI_LOAD_BONUS` in `load.py`). Alpine is not aerobic cross-training. Ride and ski kilometres are not running volume and not race-prediction inputs.
- A session under 10 minutes or under 1000 m is not "already trained".
- Garmin and Strava copies of one outing merge when starts are within 45 minutes and duration agrees. Morning + afternoon doubles stay separate. Planned Garmin `last_workout` is ignored.
- Strava date sensor wins over the activity attribute when they disagree (`DATE MISMATCH` in the log).
- Recovery wins over the calendar and over weekly quotas. `poor` or Oura rest mode → rest. `ok` uses the low end of the km range and downgrades quality/long. Gates are in `pick_session_type` and `overlay_calendar`; change both if the rule is shared.
- No race (`distance` `none` or no date): quota picker only. Race set: periodized skeleton through race day, then Monte Carlo. Book plans are not copied.
- Long-run kilometres are floored at 2.2× weekday easy or ~90 minutes at easy pace (`load.long_run_floor_km`, `periodize._long_center`). Do not size longs from the median of barely-long sessions.
- Day activity (steps, calories, intensity) is fused from Oura Activity + Garmin totals. It explains the day. It does not mark the day trained.
- Feelings, did-plan, skip reason, and effort fit are helpers and `feedback_history`. They are not add-on options.
- DuckDB `TIMESTAMP` is UTC without tzinfo (`_utc_naive`). Live file is `/data/coach.duckdb` (locked, never auto-pruned). Share copy is `/share/training_coach/coach.duckdb`, written after morning notify, after `fetch_sessions`, and at 23:00. Other apps open the copy read-only.
- Schema changes: add an idempotent `ALTER` in `CoachStore.migrate` and bump `SCHEMA_VERSION`. Backfill CTL/ATL when new load columns appear on a non-empty `sessions` table.

Tune behavior in the module that owns the constant (`INTENSITY`, `CTL_TAU` / `ATL_TAU`, ladders, `PEAK_LONG_KM`, `HARD_SPACING_HOURS`, `TSB_OVERREACH`, Monte Carlo draw counts). Those are code constants, not add-on options. `simulate.py` uses stdlib `random` only.

## Tests

From the repo root:

```bash
python3 -m unittest discover -s training_coach/tests -v
```

| File | Covers |
|---|---|
| `test_planner.py` | Classify, recovery bands, weekly quota picker, Strava/Garmin fixtures. |
| `test_race_plan.py` | Paces, periodize, finish Monte Carlo, feedback copy, calendar overlay. |
| `test_splits.py` | Split classification and applying splits onto history. |
| `test_store.py` | DuckDB upserts, migrations, share copy. |
| `test_prefs.py` | Goal parsing, prefs history, helper creation. |
| `test_schedule.py` | Morning/evening/share slot firing. |
| `test_ha_ws.py` | Websocket URL and action-day parsing. |

A PR that touches this directory must bump `version` in `config.yaml` (see the repo root `AGENTS.md`). Personal defaults (`notify.tg_oskari`, `sensor.strava_oskari_vuorinen`, `Europe/Helsinki`) stay unless the task is to change them.
