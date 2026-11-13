# Training load

[Back to the add-on README](../README.md)

Session load is a systemic impulse. A Strava suffer score is used when the session has one: suffer points per minute, clamped to **0.2–1.2**, times the duration. Otherwise a heart rate and a max (the reference max when the morning ingest has it, otherwise the session max) become a Banister TRIMP, scaled so a heart-rate reserve of **0.60** weighs the same as an easy minute (**0.60**). Resting heart rate in that reserve is **60** when the session does not carry one. With neither signal, load is duration in minutes times the type intensity below. The time constants stay code constants. They are not add-on options. The type is chosen first, using the reference max heart rate in [Session categories](sessions.md#reference-heart-rate). This table is the fallback intensity.

Code: [`session_load`](../core/src/coach/load.py#L119-L140).

## Intensity

| Type | Intensity per minute |
|---|---|
| `intervals` | 0.95 |
| `tempo` | 0.85 |
| `long_run` | 0.70 |
| `easy_run` | 0.60 |
| `cross_long` (legacy) | 0.65 |
| `cross_easy_long` | 0.55 |
| `cross_hard` | 0.80 |
| `cross_easy` | 0.45 |
| `strength` | 0.40 |
| `other` | 0.50 |
| `rest` | 0 |

Nordic or skate ski adds **0.08** on top of the cross intensity, capped at **0.95** so a ski session is never scored harder than intervals ([`SKI_LOAD_BONUS`](../core/src/coach/load.py#L61-L62)). Alpine days are `other` only when they are classified at all; they are not given the ski bonus. See [Session categories](sessions.md). The ski bonus applies on the type-intensity fallback. A suffer score or a heart-rate impulse replaces that fallback.

If duration is missing and distance is present, duration is estimated at **6:00/km** and then multiplied by the intensity.

## CTL, ATL, TSB

Banister-style exponential averages of daily session load ([`ctl_atl_tsb`](../core/src/coach/load.py#L258-L277)):

- **CTL** (fitness), time constant **42** days. Rides and skis raise it.
- **ATL** (fatigue), time constant **7** days. The same systemic impulse, so a long ride adds fatigue.
- **running_ctl** walks only `easy_run`, `long_run`, `intervals`, and `tempo`. The pace model reads this. A ride does not move it.
- **TSB** (form) = CTL − ATL. The calendar search scores the form at the end of the candidate week, with ATL multiplied by **fatigue_gain**, and penalizes that form below **−25**. The gain starts at **1** and is fit in [`performance.py`](../core/src/coach/performance.py#L302-L349); the time constants are not. See [How a day is chosen](planning.md#finish-time-and-the-small-search).

Once the history from the first session to today is at least **28** days, CTL and ATL start from the mean daily load of those first 28 days, rest days included, instead of from 0. A shorter history still starts at 0.

The morning rebuild fits that gain from easy pace at heart rate and from good-morning check-ins, then multiplies it by the readiness factor ([`readiness_factor`](../core/src/coach/performance.py#L377-L462)). The product is clamped to **0.6–1.8**. The factor stays **1** until stored mornings track the easy-pace residual. Those mornings are `recovery_daily`: Oura HRV balance, the Garmin HRV ratio, and Oura temperature deviation. Resting heart rate is not in that table, so it is not part of the factor. The factor does not vote on today's recovery band.

Each stored session also gets CTL/ATL immediately before and after that session’s own load, walked in start-time order ([`annotate_session_banister`](../core/src/coach/load.py#L156-L211)). The planning snapshot and `load_daily` still use the day-summed values, so a multi-session day can differ slightly between the session row and the daily row.

`load_daily` is written when the morning plan rebuilds the calendar, and again at the evening check-in: CTL, ATL, TSB, that day’s load, and the last 7 days of load and running kilometres. The morning notification prints the 7-day sum from the morning snapshot. The evening recap prints today’s load and the 7-day sum after today’s sessions are included. See [Notifications](notifications.md).

## What counts as running volume

[`weekly_km`](../core/src/coach/load.py#L324-L334) sums kilometres only for `easy_run`, `long_run`, `intervals`, and `tempo`. Ride and ski kilometres raise CTL/ATL through session load. They do not enter weekly running volume, `running_ctl`, the easy-pace history, or the Riegel prediction.

The long-run floor used by the calendar is [`long_run_floor_km`](../core/src/coach/load.py#L317-L321): **2.2×** weekday easy (easy kilometres clipped to 5–12), or **90 minutes** at easy pace, whichever is larger. When easy pace is missing or 4:00/km or faster, the 90-minute side uses 6:00/km. A week whose longest run is under **9 km** does not count as a long-run week when estimating typical long distance.

## Day activity is separate

Steps, active calories, and intensity minutes are fused from Oura Activity and Garmin daily totals in [`collect_day_activity`](../core/src/coach/features.py#L479-L515). The fused value is the higher of the two sources. The evening recap prints them. They do not create a session, do not mark the day trained, and do not move CTL. A high step count can still be named in the morning reasons; see [Recovery bands](recovery.md).
