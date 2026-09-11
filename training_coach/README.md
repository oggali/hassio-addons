# Training Coach

Morning training recommendation for Home Assistant OS / Supervised. The add-on reads **Oura**, **Garmin**, and **Strava** sensors already present in Home Assistant, then publishes today’s session and optionally sends Telegram.

v1 is a physiology + weekly-structure planner. It is not medical advice.

## Session types

| Type | Meaning |
|---|---|
| `rest` | Rest / recovery day |
| `easy_run` | Easy conversational / zone 2 run |
| `long_run` | Longer easy run (weekend bias) |
| `intervals` | Short hard repeats |
| `tempo` | Comfortably hard threshold block |
| `strength` | Gym / strength |

Hard sessions are `intervals` and `tempo`. A long run is taxing but not a quality day. Bike, ski, badminton and similar sports are **not** recommended, but they still count as load if they appear in Strava.

## How it decides

1. **Recovery band** (`poor` / `ok` / `good`) from Oura (primary) and Garmin (confirm): readiness, sleep, HRV vs baseline, temperature deviation, body battery, recovery time, rest mode.
2. **Sessions** from a local DuckDB warehouse of normalized coaching facts (classified Strava activities + splits). Live Strava slots and current splits are upserted each run. HA recorder history is used only once to **seed** the DB (365-day lookback on first start or after wipe), not re-pulled every morning.
3. **Weekly targets** (configurable): 1 long, 1 quality (intervals or tempo, alternating), 2 strength, 1 rest, remaining easy.
4. **Gates**: rest mode or poor recovery → rest. No hard session within 48 hours of a hard or long day. Strength is preferred when recovery is only okay.

Each recommendation includes a short **why**.

## Local DuckDB store

Path: `/data/coach.duckdb` (kept forever; no auto-prune).

| Table | What |
|---|---|
| `sessions` | Classified workouts (type, title, sport, date, duration, distance, HR, splits) |
| `recovery_daily` | Morning recovery snapshot used for the plan |
| `decisions` | Published plan + settings / session fingerprint for later feedback |

### Wipe and re-seed

To clear the local store and rebuild from HA history:

```yaml
service: hassio.addon_stdin
data:
  addon: local_training_coach
  input: wipe_db
```

Use your real add-on slug if it differs (Supervisor → Add-on → Info). After wipe, the next plan run re-seeds with a 365-day history lookback.

## Home Assistant entities created

- `sensor.training_coach_session` — `rest` / `easy_run` / `long_run` / `intervals` / `tempo` / `strength`  
  Attributes: `title`, `details`, `duration_min`, `why`, `recovery_band`, `yesterday`, `week_counts`
- `sensor.training_coach_summary` — human-readable title plus full text in `text`

## Configuration

All options are in the add-on UI.

| Option | Default | Notes |
|---|---|---|
| `timezone` | `Europe/Helsinki` | Used for “today” / weekend |
| `run_time` | `07:30` | Morning plan time |
| `oura_wait_minutes` | `90` | Wait for Oura readiness to update after `run_time` |
| `poll_seconds` | `60` | How often to re-check Oura while waiting |
| `notify_service` | `notify.tg_oskari` | HA notify service |
| `run_immediately_on_start` | `true` | Plan once on startup (does not wait for Oura) |
| `strava_entity_prefix` | `sensor.strava_oskari_vuorinen` | Prefix for recent-activity sensors |
| `weekly_long_runs` | `1` | |
| `weekly_quality_runs` | `1` | Intervals or tempo |
| `weekly_strength` | `2` | |
| `weekly_rest_days` | `1` | |
| `long_run_min_minutes` | `75` | Duration used to classify unlabeled long runs |

### Sensors read (defaults)

Oura: `sensor.oura_ring_readiness_score`, `sensor.oura_ring_sleep_score`, `sensor.oura_ring_average_sleep_hrv`, `sensor.oura_ring_hrv_balance_score`, `sensor.oura_ring_temperature_deviation`, `binary_sensor.oura_ring_rest_mode`

Garmin: `sensor.garmin_connect_training_readiness`, `sensor.garmin_connect_morning_training_readiness`, `sensor.garmin_connect_recovery_time`, `sensor.body_battery_most_recent`, `sensor.hrv_status`, `sensor.garmin_connect_hrv_last_night_average`, `sensor.garmin_connect_hrv_baseline`

Strava: `sensor.strava_oskari_vuorinen_recent_activity` and `_2` … `_10`, plus `_date`, `_distance`, `_moving_time`, `_elapsed_time`, `_average_heartrate`, `_max_heartrate`

Splits: `sensor.strava_latest_splits` (pyscript). State is the latest run’s split count; attributes `splits_metric` / `laps` / `activity_id` / `activity_name`. Older activities are seeded from recorder history into DuckDB once.

## Installation

This repository is already an add-on store repo (`repository.yaml`). After pushing:

1. Home Assistant → **Settings → Add-ons → Add-on Store**
2. The **Training Coach** add-on should appear under this repository
3. Install, start, check the log for `Plan: …`

Local planner tests (no Home Assistant required):

```bash
python3 -m unittest discover -s training_coach/tests -v
```
