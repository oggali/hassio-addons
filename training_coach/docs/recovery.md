# Recovery bands

[Back to the add-on README](../README.md)

Morning recovery is one of `poor`, `ok`, or `good`. Oura is the primary vote. Garmin confirms or disagrees. The band is what the planner reads; the individual scores are kept on the recovery row and in the “why” text.

Code: [`score_recovery`](../app/features.py#L165-L265).

## Votes

Each input below adds one poor vote or one good vote. Missing values are skipped. Oura rest mode adds **three** poor votes by itself.

| Input | Poor | Good |
|---|---|---|
| Oura readiness | &lt; 60 | ≥ 75 |
| Oura sleep | &lt; 60 | ≥ 75 |
| Garmin sleep | &lt; 60 | ≥ 75 |
| Garmin training readiness | &lt; 55 | ≥ 75 |
| Body battery | &lt; 30 | ≥ 60 |
| Oura HRV balance | &lt; 70 | ≥ 80 |
| Garmin overnight HRV / baseline | &lt; 0.90 | ≥ 1.00 |
| Garmin HRV status `unbalanced`, `low`, or `poor` | one poor vote | — |
| Oura temperature deviation | absolute value ≥ 0.5 °C | — |
| Garmin recovery time | ≥ 24 h | ≤ 8 h |

Garmin recovery time: a raw value above 48 is treated as minutes and divided by 60. Otherwise it is already hours.

Garmin training readiness may be a number or a word. Words map in [`_garmin_readiness_score`](../app/features.py#L142-L162): prime 90, productive 80, moderate 65, detraining 50, strained 48, poor 45, recovery 42, unproductive 40. A number from 1 to 10 is multiplied by 10 first.

## Which band

In order ([`score_recovery`](../app/features.py#L238-L245)):

1. **`poor`** if rest mode is on, or there are **2 or more** poor votes, or Oura readiness is under **55**.
2. **`good`** if there are no poor votes, at least **3** good votes, and Oura readiness is missing or at least **75**.
3. **`good`** if there are no poor votes, at least **1** good vote, and Oura readiness is missing or at least **70**.
4. Otherwise **`ok`**.

The reason strings (the low scores, rest mode, temperature) are what the morning “why” quotes. At most the first three are shown. High day activity can append another reason — 12k steps, or 45 intensity minutes — and does not change the band ([`add_activity_reasons`](../app/features.py#L420-L426)).

## What the band changes

The gates are in [How a day is chosen](planning.md). Short version:

- `poor` or Oura rest mode → rest, including when the race calendar wanted something else.
- `ok` → low end of the kilometre range, and quality or long becomes easy or strength.
- `good` → the calendar or the weekly quotas can prescribe quality or long, still subject to the 48h gap.

Day activity (steps, calories, intensity) is collected in the same snapshot and is not part of the band. See [Training load](load.md).
