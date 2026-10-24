# How a day is chosen

[Back to the add-on README](../README.md)

Recovery wins over both paths below. Session types are in [Session categories](sessions.md). The recovery vote is in [Recovery bands](recovery.md). Load numbers are in [Training load](load.md).

Morning always rebuilds a skeleton and replaces `plan_days` ([`rebuild_calendar`](../app/main.py#L300-L319)). Today’s published session uses that row only when a race is set (`prefs.has_race` in [`run_once`](../app/main.py#L612-L631)). The upcoming-week list on the session sensor is the skeleton either way.

## No race

`race_distance` `none`, or no race date: today comes from [`pick_session_type`](../app/planner.py#L153-L230). The stored calendar is still built, for 13 days, phase `base`, and shown as the upcoming week. It does not override today.

Weekly caps come from the helpers (`weekly_long_runs` default 1, `weekly_quality_runs` 1, `weekly_strength` 2, `weekly_rest_days` 1). Counts are training sessions in the last 7 days ([`summarize_week`](../app/planner.py#L102-L129)). A hard ride increments the hard-gap clock. It does not increment the quality or long quota. Easy rides and long easy rides do neither.

The hard gap is [`HARD_SPACING_HOURS`](../app/planner.py#L39-L41) = **48**, measured from **noon** on the hard or long day ([`datetime_hours_since`](../app/planner.py#L132-L136)). A Monday session is about 19.5 hours before Tuesday 07:30 and about 43.5 hours before Wednesday 07:30, so both of those morning plans are still inside the gap. Thursday 07:30 is the first morning plan past 48 hours. The picker also refuses a hard day when yesterday itself was hard-or-long, which already blocks the next calendar day.

Decision order:

1. A training session already logged today → rest.
2. Oura rest mode → rest.
3. Yesterday hard-or-long and today’s band `poor` → rest.
4. Band `poor` → rest.
5. Yesterday was quality or `cross_hard`, and the band is `ok` or `good` → strength if that quota is open, otherwise easy.
6. Yesterday was `long_run` or legacy `cross_long` → rest unless the band is `good`, in which case easy.
7. Band `ok` → rest if yesterday was hard-or-long; otherwise strength if that quota is open; rest if there are already 5 training days and at least 5 sessions other than strength; otherwise easy.
8. Band `good`, long quota open, weekend (Saturday or Sunday), and the hard gap has elapsed → long run.
9. Quality quota open and the gap has elapsed → intervals or tempo, whichever was not the last quality session ([`next_quality`](../app/planner.py#L147-L150)).
10. Long quota still open on Friday, gap elapsed → long run.
11. Strength quota open → strength.
12. Fewer rest days than the helper asks, and already 5 training days → rest.
13. Otherwise easy.

`cross_easy` and `cross_easy_long` do not appear in steps 5–6. The day after one of those can still be quality or long.

## Race set

A distance in `5k` / `10k` / `half` / `marathon` plus a date turns on the calendar. Today’s published session is that day’s row passed through [`overlay_calendar`](../app/planner.py#L233-L291).

Changing a helper rebuilds the remaining days without a notification. Book plans are not copied.

### Phases

[`phase_for`](../app/goal.py#L170-L189), from days left until the race:

| Phase | When |
|---|---|
| `race` | race day (0 days left) |
| `taper` | last **10** days for 5k/10k, last **14** for half and marathon |
| `peak` | the 3 weeks before taper |
| `build` | the 7 weeks before peak |
| `base` | anything earlier, and every day when no race is set |

The stored calendar ends on race day, or 13 days out when there is no race ([`end_of_plan`](../app/goal.py#L202-L205)).

### Week template

[`week_template`](../app/periodize.py#L109-L181) fills Monday=0 … Sunday=6, then repeats. Preference order, skipped when the slot is already taken by something more specific:

| Slot | Tried first |
|---|---|
| Rest | Sun, Fri, Mon, Wed |
| Long | Sat, Sun, Fri, then any easy day |
| Quality (placed as intervals, then alternated) | Tue, Thu, Wed, then any easy day |
| Strength | Mon, Wed, Fri, Thu. Can replace a rest day once rest has been placed |

Counts are the live helpers, so asking for 0 long runs leaves no long day.

### Quality ladders

Interval rungs are `(reps, metres)`. Tempo rungs are minutes at threshold, with about 15 minutes easy before and 10 after. Tables: [`INTERVAL_LADDERS`](../app/periodize.py#L40-L46), [`TEMPO_LADDERS`](../app/periodize.py#L49-L55).

| Distance | Intervals | Tempo minutes |
|---|---|---|
| 5k | 6×400, 8×400, 10×400, 6×800, 8×800 | 15, 18, 20 |
| 10k | 5×800, 6×800, 8×800, 5×1000, 6×1200 | 20, 22, 25 |
| half | 4×1000, 5×1000, 6×1000, 4×1600, 5×1600 | 20, 25, 30 |
| marathon | 4×1000, 5×1200, 4×1600, 3×2000 | 25, 30, 40 (labelled marathon-pace / threshold) |
| no race | 6×400, 8×400, 6×800 | 20, 25, 30 |

[`_ladder_index`](../app/periodize.py#L227-L252) finds the rung closest to the last session of that kind (intervals against the interval ladder, tempo against the tempo ladder). Two inputs are shared by both ladders:

- Feeling is **yesterday’s** check-in (`run_once` reads that one row), not the feeling stored on the quality day.
- Compliance is the value stored on the most recent quality day, intervals or tempo. A later Did it / Changed / Skipped tap may already have replaced the automatic compliance.

Then:

- Yesterday’s feeling `tired` or `wiped`, or stored compliance `skipped` → one rung down. Both at once is still one rung, not two.
- Stored compliance `substituted` (the Changed / `did_plan: modified` value) and yesterday not tired → hold the rung.
- Yesterday’s feeling `great`, `ok`, unset, or missing, and compliance is not one of those hold/drop cases → one rung up.
- No prior session of that kind, and yesterday tired or wiped → rung 0.

`sore` is included in the tired check in code. The feeling helper has no `sore` option; sore is a skip reason.

Taper drops one extra rung, and the quality kilometre centre is multiplied by **0.75**. Weeks alternate intervals and tempo ([`_quality_for_week`](../app/periodize.py#L255-L260)).

Kilometre half-widths: quality **12%**, long **8%**, easy **18%** of the centre ([`KM_SPREAD_*`](../app/periodize.py#L76-L80)).

### Long-run kilometres

[`_long_center`](../app/periodize.py#L278-L309) starts from the larger of recent long history and [`long_run_floor_km`](../app/load.py#L226-L230): **2.2×** weekday easy, or **90 minutes** at easy pace. It grows toward [`PEAK_LONG_KM`](../app/periodize.py#L60-L66) at **12%** per week (`LONG_WEEKLY_GROWTH`).

| Distance | Peak long |
|---|---|
| 5k | 14 km |
| 10k | 16 km |
| half | 20 km, also capped near 90% of the race |
| marathon | 32 km, also capped near 85% of the race |
| no race | 18 km |

5k and 10k peaks are not shrunk down to the race distance. Taper longs are **55%** of the current/peak value, at least 6 km. Race day is the race distance. A marathon peak long is labelled “last 3–5 km at race pace”; the pace band is still the easy band until race day.

Weekday easy is the recent easy-run median, clipped to **5–12 km**, times 0.95 in peak and 0.7 in taper (floor 4 km) ([`_easy_center`](../app/periodize.py#L312-L319)).

### Recovery overlay

[`overlay_calendar`](../app/planner.py#L233-L291) can replace today’s skeleton row:

1. Already trained, rest mode, or band `poor` → rest. Same rules as the quota picker.
2. Band `ok` and the row is hard-or-long → strength if that quota is open, otherwise easy, and the recipe uses the **low** end of the kilometre range.
3. Band `ok` and the row is easy, strength, or rest → keep it, low end of the range.
4. Band `good` but the row is hard-or-long inside the 48h gap, or yesterday was hard-or-long → easy.
5. Otherwise keep the calendar row.

`cross_easy_long` is not hard-or-long, so it does not trip step 4.

## Paces

[`build_paces`](../app/paces.py#L209-L299). Easy pace is the median pace of easy runs in the last 180 days (fallback: easy and long runs, then 6:00/km). If a race pace exists, easy becomes the **slower** of that median and race pace + **0.75 min/km** (45 s/km). The published easy band is ±20 s/km, clipped to 3:30–9:30/km.

Race prediction uses Riegel: `t2 = t1 × (d2 / d1) ^ k`. Default `k` is **1.06**, clipped to **0.8–1.3**. `k` is fitted when there are at least two running efforts of 3 km or more whose distances differ by 25%, weighted toward quality sessions and toward the last 18 months ([`fit_riegel_k`](../app/paces.py#L174-L194)). Efforts are runs of at least 1.5 km and 6 minutes, pace between 2:30 and 10:00/km. Bike and ski kilometres are not efforts.

A target time is used for training zones only when it is at least **92%** of the predicted time (`TARGET_VS_PREDICTED_FLOOR`). Faster than that, zones stay on the history-based prediction. Interval pace centres on the 5k equivalent. Tempo centres on the 10k equivalent, the halfway point of 5k and 10k for a 10k race, the half-marathon equivalent for a half, and halfway between half-marathon and race pace for a marathon. Quality bands are ±10 s/km. A recent quality session faster than the band pulls the centre halfway toward that observed pace, and not below the equivalent minus 5 s/km.

## Finish time and the small search

[`simulate.py`](../app/simulate.py#L21-L33) uses the standard library random number generator.

- **500** draws around the Riegel prediction publish P10 / P50 / P90 and the chance of beating the target. Relative spread is about **11%** (`REL_VAR`). Most draws are near the prediction (70%), some are slower (25%), a few are outliers.
- The target is feasible when it is not faster than P10 × **0.98**. If it is faster than that, the search is skipped and long-run volume is capped ([`_safe_volume`](../app/simulate.py#L192-L222)).
- Otherwise the skeleton is scored once, then **10** mutations are each averaged over **80** sims ([`search_calendar`](../app/simulate.py#L279-L332)). A mutation drops a quality day to easy, shrinks a long run by 10%, or swaps an easy day with a rest day. Lower score wins. The score rewards a higher chance of hitting the target and penalizes training-stress balance below **−25**, a week that jumps more than 15% in kilometres, back-to-back hard days, and the feedback penalties in [Evening feedback](feedback.md#what-the-next-plan-reads).
