# Training Coach

Morning and evening training recommendation for Home Assistant OS / Supervised. The add-on reads **Oura**, **Garmin**, and **Strava** sensors already present in Home Assistant, then publishes today’s session, a race-goal prediction, and Telegram (always). Optional Android Companion notifications can duplicate those messages and collect evening button replies.

v1 is a physiology + weekly-structure + optional race-goal planner. It is not medical advice.

## Session types

| Type | Meaning |
|---|---|
| `rest` | Rest / recovery day |
| `easy_run` | Easy conversational / zone 2 run |
| `long_run` | Longer easy run (weekend bias) / race day |
| `intervals` | Short hard repeats |
| `tempo` | Comfortably hard threshold / marathon-pace block |
| `strength` | Gym / strength |
| `cross_easy` | Easy bike / nordic ski / swim (not prescribed; logged from Strava) |
| `cross_hard` | Hard bike or ski intervals, races, high-HR sessions |
| `cross_long` | Long endurance ride or ski |

Hard running sessions are `intervals` and `tempo`. A long run is taxing but not a quality day. Bike and **nordic / skate ski** are not recommended as the day’s session, but Strava still counts them. Easy spins or classic technique do not block a quality run; hard or long rides/skis raise CTL/ATL and use the same next-day recovery gates as a hard or long run. Ski minutes count a bit heavier than the same time on the bike (more legs). Downhill alpine days are ignored as aerobic cross-training. Ride/ski km do not count toward running volume or race-time prediction.

Morning lines look like `Easy run  6–10 km  @  5:50–6:30 /km` or `Intervals  8–11 km  @  4:20–4:35 /km  (8×400 m, jog recoveries)`.

## How it decides

1. **Recovery band** (`poor` / `ok` / `good`) from Oura (primary) and Garmin (confirm).
2. **Sessions** from a local DuckDB warehouse of classified Strava activities + splits. HA recorder history seeds the DB once (365-day lookback).
3. **Live prefs** (Home Assistant helpers, not add-on config): race date / distance / target time and weekly long / quality / strength / rest caps. Changing a helper does **not** restart the add-on; the coach polls and rebuilds the remaining calendar.
4. **No race set:** same daily quota picker as before (1 long, 1 quality, 2 strength, 1 rest by default).
5. **Race set:** original periodized calendar to race day (base / build / peak / taper), km + pace ranges from your easy history and Riegel equivalents of the target (or predicted) time. Interval/tempo structure varies by distance and by the last completed quality session. Long-run km is at least **2.2× weekday easy** or **~90 min** at easy pace (not the median of sessions that barely cleared the 75-min “long” tag). A small Monte Carlo search nudges remaining days; a second Monte Carlo publishes P10 / P50 / P90 finish time.
6. **Gates:** rest mode or poor recovery still wins over the calendar. Okay recovery uses the **low** end of the km range and downgrades quality/long.

Book training plans are **not** copied. The calendar uses public periodization rules and your data.

Finish-time math follows public race-prediction ideas (Riegel’s formula and a day-mixture Monte Carlo). This add-on does **not** ingest GPX, grade-binned streams, or Strava OAuth — only DuckDB sessions already classified from Home Assistant sensors.

## Evening check-in

At `evening_time` (default 20:30):

- Telegram **always** recaps planned vs what Strava logged, and names tomorrow’s calendar session.
- If **Android is off**, Telegram names the feeling / did-plan / skip-reason helpers so you can set them in HA.
- If **`mobile_notify_service` is set**, the phone gets the same recap **plus** action buttons (Android allows three). Taps write those helpers. Telegram does **not** ask questions in that case.

Skipped-vs-done is stored even if you never tap. A late run after evening is corrected the next morning.

## Live prefs (helpers)

Created on startup if missing (same helper API as **Settings → Devices & services → Helpers**; defaults match the old weekly quotas):

- `input_datetime.training_coach_race_date`
- `input_select.training_coach_race_distance` — `none` / `5k` / `10k` / `half` / `marathon`
- `input_text.training_coach_target_time` — `H:MM:SS` or `MM:SS`
- `input_number.training_coach_weekly_long_runs` (0–3)
- `input_number.training_coach_weekly_quality_runs` (0–4)
- `input_number.training_coach_weekly_strength` (0–5)
- `input_number.training_coach_weekly_rest_days` (0–4)
- `input_select.training_coach_feeling` — `unset` / `great` / `ok` / `tired` / `wiped`
- `input_select.training_coach_did_plan` — `unset` / `yes` / `modified` / `skipped`
- `input_select.training_coach_skip_reason` — `unset` / `no_time` / `tired` / `sore` / `weather` / `other_sport`

Every prefs change is appended to DuckDB `prefs_history` (old rows keep `valid_to`).

Stdin (same as wipe):

```yaml
service: hassio.addon_stdin
data:
  addon: local_training_coach
  input: '{"cmd":"set_prefs","race_distance":"half","target_time":"1:45:00","race_date":"2026-10-04"}'
```

```yaml
input: '{"cmd":"checkin","feeling":"tired","did_plan":"skipped","skip_reason":"sore"}'
```

## Local DuckDB store

Path: `/data/coach.duckdb` (kept forever; no auto-prune).

| Table | What |
|---|---|
| `sessions` | Classified workouts |
| `recovery_daily` | Morning recovery snapshot |
| `decisions` | Published morning plan |
| `prefs_history` | Race goal + weekly caps over time |
| `plan_days` | Remaining calendar after Monte Carlo search |
| `feedback_history` | Evening compliance + feeling |

### Wipe and re-seed

```yaml
service: hassio.addon_stdin
data:
  addon: local_training_coach
  input: wipe_db
```

Use your real add-on slug if it differs. After wipe, the next plan run re-seeds with a 365-day history lookback.

## Home Assistant entities created

- `sensor.training_coach_session` — session type, title, km/pace, why, upcoming week
- `sensor.training_coach_summary` — human-readable title plus full text in `text`
- `sensor.training_coach_goal` — days to race, target, **P10/P50/P90**, hit probability, CTL/TSB
- `sensor.training_coach_feedback` — last evening compliance + feeling

## Configuration (add-on UI, ops only)

| Option | Default | Notes |
|---|---|---|
| `timezone` | `Europe/Helsinki` | Used for “today” / weekend |
| `run_time` | `07:30` | Morning plan time |
| `evening_time` | `20:30` | Evening recap |
| `oura_wait_minutes` | `90` | Wait for Oura readiness after `run_time` |
| `poll_seconds` | `60` | Oura wait + helper poll interval |
| `notify_service` | `notify.tg_oskari` | Telegram (always used, morning and evening) |
| `mobile_notify_service` | *(empty)* | Optional, e.g. `notify.mobile_app_galaxys26` |
| `run_immediately_on_start` | `true` | Plan once on startup (no Oura wait). Notifies only if today’s morning slot already passed. |
| `strava_entity_prefix` | `sensor.strava_oskari_vuorinen` | Prefix for recent-activity sensors |
| `long_run_min_minutes` | `75` | Duration used to classify unlabeled long runs |

Race goal and weekly caps are **not** in this list on purpose — changing add-on options restarts the container.

### Sensors read (defaults)

Oura: `sensor.oura_ring_readiness_score`, `sensor.oura_ring_sleep_score`, `sensor.oura_ring_average_sleep_hrv`, `sensor.oura_ring_hrv_balance_score`, `sensor.oura_ring_temperature_deviation`, `binary_sensor.oura_ring_rest_mode`

Garmin: `sensor.garmin_connect_training_readiness`, `sensor.garmin_connect_morning_training_readiness`, `sensor.garmin_connect_recovery_time`, `sensor.body_battery_most_recent`, `sensor.hrv_status`, `sensor.garmin_connect_hrv_last_night_average`, `sensor.garmin_connect_hrv_baseline`

Strava: `sensor.strava_oskari_vuorinen_recent_activity` and `_2` … `_10`, plus `_date`, `_distance`, `_moving_time`, `_elapsed_time`, `_average_heartrate`, `_max_heartrate`

Splits: `sensor.strava_latest_splits` (pyscript).

## Installation

This repository is already an add-on store repo (`repository.yaml`). After pushing:

1. Home Assistant → **Settings → Add-ons → Add-on Store**
2. The **Training Coach** add-on should appear under this repository
3. Install, start, check the log for `Plan: …`
4. Set race date / distance / target on the helpers (Developer Tools or a Lovelace card)

Local tests (no Home Assistant required):

```bash
python3 -m unittest discover -s training_coach/tests -v
```
