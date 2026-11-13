# How a day is chosen

[Back to the add-on README](../README.md)

Recovery wins over both paths below. Session types are in [Session categories](sessions.md). The recovery vote is in [Recovery bands](recovery.md). Load numbers are in [Training load](load.md).

Morning always rebuilds a skeleton and replaces `plan_days` ([`rebuild_calendar`](../app/main.py#L338-L372)). Today’s published session uses that row when a race is set, and also when today is a weekday lock (`run_once` in [`main.py`](../app/main.py#L691-L760)). The upcoming-week list on the session sensor is the skeleton either way.

## No race

`race_distance` `none`, or no race date: today comes from [`pick_session_type`](../core/src/coach/planner.py#L184-L275), unless today is a weekday lock. A locked today uses the calendar row. The stored calendar is still built, for 13 days, phase `base`, and shown as the upcoming week. Unlocked days in that list do not override today.

Weekly caps come from the helpers (`weekly_long_runs` default 1, `weekly_quality_runs` 1, `weekly_strength` 2, `weekly_rest_days` 1). Counts are training sessions in the last 7 days ([`summarize_week`](../core/src/coach/planner.py#L133-L161)). A lock on a day in that window counts toward the same bucket when that day did not already log it ([`apply_lock_quota`](../core/src/coach/planner.py#L102-L131)). A missed Monday intervals still uses the quality cap. A hard ride increments the hard-gap clock. It does not increment the quality or long quota. Easy rides and long easy rides do neither.

The hard gap is [`HARD_SPACING_HOURS`](../core/src/coach/planner.py#L40-L42) = **48**, measured from **noon** on the hard or long day ([`datetime_hours_since`](../core/src/coach/planner.py#L163-L167)). A Monday session is about 19.5 hours before Tuesday 07:30 and about 43.5 hours before Wednesday 07:30, so both of those morning plans are still inside the gap. Thursday 07:30 is the first morning plan past 48 hours. The picker also refuses a hard day when yesterday itself was hard-or-long, which already blocks the next calendar day. It also refuses a new hard day when tomorrow is a locked hard day. Unlocked days keep this 48-hour rule. A locked hard day uses the two-night rule in [Weekday locks](#weekday-locks).

Decision order:

1. A training session already logged today → rest.
2. Oura rest mode → rest.
3. Yesterday hard-or-long and today’s band `poor` → rest.
4. Band `poor` → rest.
5. Yesterday was quality or `cross_hard`, and the band is `ok` or `good` → strength if that quota is open, otherwise easy.
6. Yesterday was `long_run` or legacy `cross_long` → rest unless the band is `good`, in which case easy.
7. Band `ok` → rest if yesterday was hard-or-long; otherwise strength if that quota is open; rest if there are already 5 training days and at least 5 sessions other than strength; otherwise easy.
8. Band `good`, long quota open, weekend (Saturday or Sunday), and the hard gap has elapsed → long run.
9. Quality quota open and the gap has elapsed → intervals or tempo, whichever was not the last quality session ([`next_quality`](../core/src/coach/planner.py#L178-L181)).
10. Long quota still open on Friday, gap elapsed → long run.
11. Strength quota open → strength.
12. Fewer rest days than the helper asks, and already 5 training days → rest.
13. Otherwise easy.

`cross_easy` and `cross_easy_long` do not appear in steps 5–6. The day after one of those can still be quality or long.

## Race set

A distance in `5k` / `10k` / `half` / `marathon` plus a date turns on the calendar. Today’s published session is that day’s row passed through [`overlay_calendar`](../core/src/coach/planner.py#L283-L366).

Changing a helper rebuilds the remaining days without a notification. Book plans are not copied.

### Phases

[`phase_for`](../core/src/coach/goal.py#L226-L245), from days left until the race:

| Phase | When |
|---|---|
| `race` | race day (0 days left) |
| `taper` | last **10** days for 5k/10k, last **14** for half and marathon |
| `peak` | the 3 weeks before taper |
| `build` | the 7 weeks before peak |
| `base` | anything earlier, and every day when no race is set |

The stored calendar ends on race day, or 13 days out when there is no race ([`end_of_plan`](../core/src/coach/goal.py#L258-L261)).

### Week template

[`week_template`](../core/src/coach/periodize.py#L117-L210) fills Monday=0 … Sunday=6, then repeats. Locks are written first and count toward these caps. Preference order for the remaining days, skipped when the slot is already taken:

| Slot | Tried first |
|---|---|
| Rest | Sun, Fri, Mon, Wed |
| Long | Sat, Sun, Fri, then any easy day |
| Quality (placed as intervals, then alternated) | Tue, Thu, Wed, then any easy day |
| Strength | Mon, Wed, Fri, Thu. Can replace a rest day once rest has been placed |

Counts are the live helpers, so asking for 0 long runs leaves no long day unless that weekday is locked to `long_run`. A weekly long run is the default quota, not a requirement.

### Weekday locks

Helpers `input_select.training_coach_lock_mon` through `training_coach_lock_sun`, or stdin `set_locks`, store a repeating weekday in DuckDB `weekday_locks`. Options are `unset`, `easy_run`, `long_run`, `intervals`, `tempo`, `strength`, and `rest`. `unset` deletes that row. A change rebuilds the plan without a notification, the same way as the other prefs.

Locks are placed before rest, long, quality, and strength. A locked `intervals` stays intervals every week. [`_quality_for_week`](../core/src/coach/periodize.py#L283-L289) still alternates only unlocked quality slots. Locks count toward the weekly cap. Extra locks above the cap stay. Race day still replaces a lock on that date.

An unlocked hard day (`intervals`, `tempo`, `long_run`) is not placed on the weekday next to a locked hard day. One day between hard days is enough: Saturday long and Monday intervals stay together. Sunday and Tuesday stay free of an unlocked hard day when Monday is locked intervals. Two locks on adjacent days both stay on the calendar. The later morning becomes easy when yesterday’s logged session was the other hard day.

With no race, only a locked today uses the calendar row. The picker still counts past locks in the last 7 days, and it will not schedule a hard day when tomorrow is a locked hard day. Search mutations leave `source="lock"` alone, including the kilometres of a locked long run.

Recovery still decides the published session. Already trained, rest mode, or band `poor` becomes rest, and the why text names the lock. Band `ok` still softens a hard lock. The lock stays consumed for the rest of that week.

### Quality ladders

Interval rungs are `(reps, metres)`. Tempo rungs are minutes at threshold, with about 15 minutes easy before and 10 after. Tables: [`INTERVAL_LADDERS`](../core/src/coach/periodize.py#L40-L46), [`TEMPO_LADDERS`](../core/src/coach/periodize.py#L49-L55).

| Distance | Intervals | Tempo minutes |
|---|---|---|
| 5k | 6×400, 8×400, 10×400, 6×800, 8×800 | 15, 18, 20 |
| 10k | 5×800, 6×800, 8×800, 5×1000, 6×1200 | 20, 22, 25 |
| half | 4×1000, 5×1000, 6×1000, 4×1600, 5×1600 | 20, 25, 30 |
| marathon | 4×1000, 5×1200, 4×1600, 3×2000 | 25, 30, 40 (labelled marathon-pace / threshold) |
| no race | 6×400, 8×400, 6×800 | 20, 25, 30 |

[`_ladder_index`](../core/src/coach/periodize.py#L255-L281) finds the rung closest to the last session of that kind (intervals against the interval ladder, tempo against the tempo ladder). Two inputs are shared by both ladders:

- Feeling is **yesterday’s** check-in (`run_once` reads that one row), not the feeling stored on the quality day.
- Compliance is the value stored on the most recent quality day, intervals or tempo. A later Did it / Changed / Skipped tap may already have replaced the automatic compliance.

Then:

- Yesterday’s feeling `tired` or `wiped`, or stored compliance `skipped` → one rung down. Both at once is still one rung, not two.
- Stored compliance `substituted` (the Changed / `did_plan: modified` value) and yesterday not tired → hold the rung.
- Yesterday’s feeling `great`, `ok`, unset, or missing, and compliance is not one of those hold/drop cases → one rung up.
- No prior session of that kind, and yesterday tired or wiped → rung 0.

`sore` is included in the tired check in code. The feeling helper has no `sore` option; sore is a skip reason.

Taper drops one extra rung, and the quality kilometre centre is multiplied by **0.75**. Weeks alternate intervals and tempo ([`_quality_for_week`](../core/src/coach/periodize.py#L283-L289)).

Kilometre half-widths: quality **12%**, long **8%**, easy **18%** of the centre ([`KM_SPREAD_*`](../core/src/coach/periodize.py#L78-L80)).

### Long-run kilometres

[`_long_center`](../core/src/coach/periodize.py#L306-L337) starts from the larger of recent long history and [`long_run_floor_km`](../core/src/coach/load.py#L226-L230): **2.2×** weekday easy, or **90 minutes** at easy pace. It grows toward [`PEAK_LONG_KM`](../core/src/coach/periodize.py#L60-L66) at **12%** per week (`LONG_WEEKLY_GROWTH`).

| Distance | Peak long |
|---|---|
| 5k | 14 km |
| 10k | 16 km |
| half | 20 km, also capped near 90% of the race |
| marathon | 32 km, also capped near 85% of the race |
| no race | 18 km |

5k and 10k peaks are not shrunk down to the race distance. Taper longs are **55%** of the current/peak value, at least 6 km. Race day is the race distance. A marathon peak long is labelled “last 3–5 km at race pace”; the pace band is still the easy band until race day.

Weekday easy is the recent easy-run median, clipped to **5–12 km**, times 0.95 in peak and 0.7 in taper (floor 4 km) ([`_easy_center`](../core/src/coach/periodize.py#L340-L347)).

### Recovery overlay

[`overlay_calendar`](../core/src/coach/planner.py#L283-L366) can replace today’s skeleton row:

1. Already trained, rest mode, or band `poor` → rest. Same rules as the quota picker.
2. Band `ok` and the row is hard-or-long → strength if that quota is open, otherwise easy, and the recipe uses the **low** end of the kilometre range.
3. Band `ok` and the row is easy, strength, or rest → keep it, low end of the range.
4. Band `good` but the row is hard-or-long inside the 48h gap, or yesterday was hard-or-long → easy. A locked hard day skips the 48h half of this check, so Saturday long leaves Monday intervals in place. Yesterday hard or long still makes that Monday easy.
5. Otherwise keep the calendar row. A locked row says which weekday is locked.

`cross_easy_long` is not hard-or-long, so it does not trip step 4.

## Paces

[`build_paces`](../core/src/coach/paces.py#L209-L299). Easy pace is the median pace of easy runs in the last 180 days (fallback: easy and long runs, then 6:00/km). If a race pace exists, easy becomes the **slower** of that median and race pace + **0.75 min/km** (45 s/km). The published easy band is ±20 s/km, clipped to 3:30–9:30/km.

Race prediction uses Riegel: `t2 = t1 × (d2 / d1) ^ k`. Default `k` is **1.06**, clipped to **0.8–1.3**. `k` is fitted when there are at least two running efforts of 3 km or more whose distances differ by 25%, weighted toward quality sessions and toward the last 18 months ([`fit_riegel_k`](../core/src/coach/paces.py#L174-L194)). Efforts are runs of at least 1.5 km and 6 minutes, pace between 2:30 and 10:00/km. Bike and ski kilometres are not efforts.

A target time is used for training zones only when it is at least **92%** of the predicted time (`TARGET_VS_PREDICTED_FLOOR`). Faster than that, zones stay on the history-based prediction. Interval pace centres on the 5k equivalent. Tempo centres on the 10k equivalent, the halfway point of 5k and 10k for a 10k race, the half-marathon equivalent for a half, and halfway between half-marathon and race pace for a marathon. Quality bands are ±10 s/km. A recent quality session faster than the band pulls the centre halfway toward that observed pace, and not below the equivalent minus 5 s/km.

## Finish time and the small search

[`simulate.py`](../core/src/coach/simulate.py#L22-L34) uses the standard library random number generator.

- **500** draws around the Riegel prediction publish P10 / P50 / P90 and the chance of beating the target. Relative spread is about **11%** (`REL_VAR`). Most draws are near the prediction (70%), some are slower (25%), a few are outliers.
- The target is feasible when it is not faster than P10 × **0.98**. If it is faster than that, the search is skipped and long-run volume is capped ([`_safe_volume`](../core/src/coach/simulate.py#L216-L247)). A locked long run keeps its kilometres.
- Otherwise the skeleton is scored once, then **10** mutations are each averaged over **80** sims ([`search_calendar`](../core/src/coach/simulate.py#L303-L356)). A mutation drops an unlocked quality day to easy, shrinks an unlocked long run by 10%, or swaps an unlocked easy day with an unlocked rest day. Lower score wins. The score rewards a higher chance of hitting the target and penalizes training-stress balance below **−25**, a week that jumps more than 15% in kilometres, back-to-back hard days, and the feedback penalties in [Evening feedback](feedback.md#what-the-next-plan-reads).
