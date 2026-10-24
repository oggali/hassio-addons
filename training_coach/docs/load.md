# Training load

[Back to the add-on README](../README.md)

Session load is duration in minutes times a fixed intensity. It is not heart-rate TRIMP and not Training Stress Score. The intensities and the time constants are code constants. They are not add-on options. The type is chosen first, using the reference max heart rate in [Session categories](sessions.md#reference-heart-rate). This table is the intensity for that type.

Code: [`load.py`](../app/load.py#L36-L101).

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

Nordic or skate ski adds **0.08** on top of the cross intensity, capped at **0.95** so a ski session is never scored harder than intervals ([`SKI_LOAD_BONUS`](../app/load.py#L54-L58)). Alpine days are `other` only when they are classified at all; they are not given the ski bonus. See [Session categories](sessions.md).

If duration is missing and distance is present, duration is estimated at **6:00/km** and then multiplied by the intensity.

## CTL, ATL, TSB

Banister-style exponential averages of daily session load ([`ctl_atl_tsb`](../app/load.py#L168-L186)):

- **CTL** (fitness), time constant **42** days.
- **ATL** (fatigue), time constant **7** days.
- **TSB** (form) = CTL − ATL. The calendar search penalizes TSB below **−25**. See [How a day is chosen](planning.md#finish-time-and-the-small-search).

Each stored session also gets CTL/ATL immediately before and after that session’s own load, walked in start-time order ([`annotate_session_banister`](../app/load.py#L104-L156)). The planning snapshot and `load_daily` still use the day-summed values, so a multi-session day can differ slightly between the session row and the daily row.

`load_daily` is written when the morning plan rebuilds the calendar, and again at the evening check-in: CTL, ATL, TSB, that day’s load, and the last 7 days of load and running kilometres. The morning notification prints the 7-day sum from the morning snapshot. The evening recap prints today’s load and the 7-day sum after today’s sessions are included. See [Notifications](notifications.md).

## What counts as running volume

[`weekly_km`](../app/load.py#L233-L242) sums kilometres only for `easy_run`, `long_run`, `intervals`, and `tempo`. Ride and ski kilometres raise CTL/ATL through session load. They do not enter weekly running volume, the easy-pace history, or the Riegel prediction.

The long-run floor used by the calendar is [`long_run_floor_km`](../app/load.py#L226-L230): **2.2×** weekday easy (easy kilometres clipped to 5–12), or **90 minutes** at easy pace, whichever is larger. When easy pace is missing or 4:00/km or faster, the 90-minute side uses 6:00/km. A week whose longest run is under **9 km** does not count as a long-run week when estimating typical long distance.

## Day activity is separate

Steps, active calories, and intensity minutes are fused from Oura Activity and Garmin daily totals in [`collect_day_activity`](../app/features.py#L465-L501). The fused value is the higher of the two sources. The evening recap prints them. They do not create a session, do not mark the day trained, and do not move CTL. A high step count can still be named in the morning reasons; see [Recovery bands](recovery.md).
