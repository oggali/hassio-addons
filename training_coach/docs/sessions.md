# Session categories

[Back to the add-on README](../README.md)

Logged workouts become one of the types in [`classify.py`](../app/classify.py#L29-L60). The coach never prescribes bike or ski; those types exist so Strava and Garmin history still counts.

| Type | Group | What it does to the next plan |
|---|---|---|
| `rest` | — | No session |
| `easy_run` | run | Easy day. Does not start the 48h hard gap |
| `long_run` | run, hard-or-long | Taxing. Starts the hard gap. Not a quality day |
| `intervals` | run, quality, hard-or-long | Quality. Starts the hard gap |
| `tempo` | run, quality, hard-or-long | Quality. Intervals and tempo count as the same family at check-in |
| `strength` | training | Gym. Does not start the hard gap |
| `cross_easy` | cross, training | Easy bike, nordic ski, swim, row. Load only |
| `cross_easy_long` | cross, training | Long easy ride or ski. Load only. New classifications use this, not `cross_long` |
| `cross_hard` | cross, hard-or-long | Hard ride or ski. Same next-day gate as a hard run |
| `cross_long` | cross, hard-or-long | Legacy taxing long ride or ski already stored in DuckDB. New paths do not emit it |
| `other` | — | Walk, hike, yoga, alpine ski, or anything too short to keep. Dropped from training |

Sets used by the planner live next to the constants:

- `QUALITY` — `intervals`, `tempo`
- `RUN_TYPES` — the four run types. Only these kilometres count as running volume
- `HARD_OR_LONG` — quality, `long_run`, `cross_hard`, legacy `cross_long`
- `TRAINING_TYPES` — runs, all cross types, `strength`

## What counts as already trained

[`is_training_session`](../app/classify.py#L162-L174) ignores `rest` and `other`. A training type with no duration and no distance still counts. Otherwise it needs **10 minutes** or **1000 m**. A 5-minute shakeout under 1 km does not mark the day trained.

Oura workouts are never read. Steps and calories from the ring are day activity, not a session. See [Training load](load.md).

## Which sport function runs

[`classify_sport`](../app/classify.py#L432-L468), in order:

1. Strength sport, `"weight"` in the sport name, or `"gym"` in the title → `strength`.
2. Run sport (`run`, `running`, `trailrun`, `virtualrun`), or an empty sport whose title looks like a run → [`classify_run`](../app/classify.py#L331-L379).
3. Alpine ski, snowboard, snowshoe, walk, hike, yoga, pilates → `other`.
4. Bike, nordic/skate ski, swim, row, or any other sport lasting at least 25 minutes with a heart rate → [`classify_cross`](../app/classify.py#L382-L429).
5. Anything else → `other`.

Sport names are lowercased with spaces, hyphens, and underscores removed. Bike also matches `ride`, `bike`, `cycl`, and titles containing zwift, commute, or group ride ([`is_bike_sport`](../app/classify.py#L238-L243)). Ski matches the nordic names plus titles such as `hiihto`, skate, classic, rollerski ([`is_ski_sport`](../app/classify.py#L246-L254)). A sport key that is alpine is not ski.

## Reference heart rate

Run and cross heart-rate steps divide by one personal max, [`reference_max_hr`](../app/classify.py#L297-L328). The activity’s own peak is kept on the session row and is not the denominator.

`max_heart_rate` in the add-on options is the starting value (this install: **195**). Each ingest computes the working number from stored sessions:

- The window is **183 days**.
- A max below **90** or above **230** is ignored.
- Once the oldest stored session is at least 183 days ago, the reference is the highest plausible max in the window, from a run, a ride, or any other sport. An old peak drops out when it ages past the window, and the reference can sit below the option.
- Until the store spans that long, the reference is the option. A higher plausible max inside the window replaces it for classification. The option stays as written in the add-on config.

The log line is `Heart-rate reference N bpm (setup)`, `setup raised by a session max`, or `rolling 6 months`.

On the same ingest, stored run and cross rows are classified again with that reference ([`classify_logged_session`](../app/classify.py#L488-L526)). Title words and stored kilometre splits still win, so an interval workout stays `intervals`. Session load and the CTL/ATL trace update when a type changes. The evening `feedback_history` row stays the text that was sent that night.

A steady 61-minute run averaging 148, with a peak of 159 on that outing, is `easy_run` when the reference is 195 (148 / 195 = 0.76).

## Runs

[`classify_run`](../app/classify.py#L331-L379) stops at the first match:

1. Title contains an interval word: interval, repeat, track, vo2, speed, fartlek, strides.
2. Title contains a tempo word: tempo, threshold, cruise, lactate, steady-state.
3. Splits say `intervals` or `tempo` (see below). This beats a title that only says easy or long.
4. Title contains `long` or `lsd`.
5. Title contains easy, recovery, shakeout, jog, zone 2, or z2.
6. Any other splits hint.
7. Duration at least `long_run_min_minutes` (add-on option, default **75**).
8. Heart rate against the [reference max](#reference-heart-rate). At least 20 minutes and average / reference ≥ **0.84** → `tempo`. Otherwise `easy_run`. Intervals come from the title or from splits.

## Bike, ski, and other cross-training

[`classify_cross`](../app/classify.py#L382-L429). “Long” for cross is not the run threshold. [`cross_long_minutes`](../app/classify.py#L257-L265):

- Ski: `max(80, long_run_min_minutes × 1.1)` → **82** at the default 75.
- Bike and everything else: `max(100, long_run_min_minutes × 1.4)` → **105** at the default 75.

Order:

1. Hard words (interval, vo2, ftp, sweet spot, threshold, tempo, race, zwift race, attack, sprint, over-under, ski-o, time trial) → `cross_hard`.
2. Long words (`long`, `fondo`, `adventure`, `tour`) → `cross_easy_long`.
3. Easy words (easy, recovery, commute, zone 2, endurance, technique). Duration at the long threshold upgrades that to `cross_easy_long`.
4. Heart rate against the same [reference max](#reference-heart-rate). Short efforts use a higher bar:
   - at or over the long threshold and average / reference ≥ **0.84** → `cross_hard`, otherwise `cross_easy_long`
   - over 40 minutes and ratio ≥ **0.84** → `cross_hard`
   - at least 25 minutes and ratio ≥ **0.86** → `cross_hard`
5. Duration at the long threshold, with no hard heart rate → `cross_easy_long`.
6. E-bike with nothing else matching → `cross_easy`.
7. Under 12 minutes → `other`.
8. Otherwise `cross_easy`.

## Splits

`sensor.strava_latest_splits` can reclassify a **run** after the title pass. Strength and cross types are left alone ([`_reclassify`](../app/splits.py#L257-L280)). The same reference max is passed through, so attaching splits does not put the activity’s own peak back in the denominator.

[`classify_from_splits`](../app/splits.py#L112-L158):

- Five or more laps, five or more of them 200–1200 m, and at least three laps ≥ 0.35 min/km faster than the median pace → `intervals`. Lap names containing interval/repeat or tempo/threshold do the same.
- On kilometre splits (pace between 2.5 and 12 min/km): two or more kilometres that are ≥ 0.35 min/km faster than both neighbours → `intervals`.
- Three or more steady kilometres ≥ 0.35 min/km faster than the first split, with a standard deviation ≤ 0.20 → `tempo`.
- A wide spread through the middle of the run (standard deviation ≥ 0.40 and range ≥ 0.8 min/km) → `intervals`.

Splits attach by Strava activity id. A title match is used only when the session has no id and exactly one split set fits, so a repeated title such as “Afternoon Run” does not steal the previous run’s id ([`_match_split`](../app/splits.py#L230-L254)).

## Garmin and Strava copies of one outing

[`sessions_look_same`](../app/classify.py#L690-L732) and [`merge_training_sessions`](../app/classify.py#L735-L753):

- Same activity id → same outing.
- Different sport families (run vs bike vs ski vs gym) stay separate.
- Both have a clock time: starts within **45 minutes**, and durations within **20 minutes** (or both missing). Morning and afternoon doubles stay separate.
- Date only, no clock: durations within **5 minutes** and distances within **25%**. That keeps two similar-length sessions on the same day apart.
- When they merge, Strava is kept over Garmin, and Garmin over an older history stub.

Strava distance sensors are treated as kilometres when the number is under 1000, and as metres otherwise ([`strava_distance_metres`](../app/classify.py#L190-L199)). Garmin distance is metres. Garmin duration is seconds.

Strava’s date sensor wins when it disagrees with the activity attribute. The log line is `DATE MISMATCH`.

Entry points: [`session_from_strava_slot`](../app/classify.py#L534-L581), [`session_from_garmin_activity`](../app/classify.py#L599-L651). History is merged in [`collect_live_sessions`](../app/features.py#L445-L471). Garmin’s planned `last_workout` sensor is not read.
