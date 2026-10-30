# Notifications

[Back to the add-on README](../README.md)

Telegram (`notify_service`) is always used. Android (`mobile_notify_service`) receives the morning message when that service is set. The evening recap goes to Telegram; the phone gets the same recap on the first card, then short follow-up cards. Categories and buttons are in [Evening feedback](feedback.md). The load numbers are in [Training load](load.md).

[`notify_message`](../app/main.py#L450-L482) sets `data.parse_mode` to `plain_text` on every Telegram send. The legacy notify platform forwards that to `telegram_bot.send_message`. Without it, the bot’s default parser is legacy Markdown, where `_` starts italics. `same_family` in the evening recap, and helper entity ids when Android is off, have no closing `_`, so Telegram rejects the message and nothing is delivered. Android cards do not set a parse mode.

## Morning

[`notify_plan`](../app/main.py#L485-L504) sends this when the morning slot runs and the add-on is allowed to notify. The slot waits until Oura looks updated today and Garmin has a wake snapshot (see [Recovery bands](recovery.md)). The wait ends at `run_time` plus `oura_wait_minutes`, and not before three hours. After that the plan is sent from Oura, without yesterday’s Garmin sleep score or the in-bed body battery. A startup plan notifies only if `run_time` has already passed and today’s morning notify has not been sent, and that notify uses the same wait.

```
Today: Easy run
6–10 km @ 5:50–6:30 /km

Why: Recovery is good.
Recovery: good
Training load: 7-day 186.

Upcoming:
Tue: easy run 6–10 km @ 5:50–6:30
```

`7-day` is the rolling 7 days through this morning, the same sum as `load_daily.weekly_load`: minutes times intensity for every logged session in that window, including a session already stored today. A run that shows up later is in the evening number, not this one. Zero is printed when the window is empty. Today’s own load is left off the morning message.

The upcoming block is the next seven calendar rows. Without a race, those rows are the 13-day skeleton and do not override the session in the “Today” line. See [How a day is chosen](planning.md).

## Evening

[`recap_text`](../app/feedback.py#L305-L353) builds the Telegram message and the first Android card ([`run_evening`](../app/main.py#L787-L820)):

```
This morning: Easy run
Logged: easy run 8.2 km (planned easy run → match).
Nice — that matches the morning plan. Tomorrow: gym / strength.
Training load: today 24, 7-day 186.
Day activity: 11.0k steps, 430 kcal (Garmin + Oura).
```

`today` is session load dated today. `7-day` is that same rolling sum, now including today. Both come from the snapshot written to `load_daily` at check-in ([`format_load_line`](../app/feedback.py#L257-L270)). A rest day with nothing logged prints `today 0`.

Day activity (steps, calories, intensity minutes) is a separate line. Those figures are not added into training load.

The feeling, skip-reason, and effort cards that follow on Android are short prompts. They do not repeat the load line. When Android is off, the Telegram recap also names the helpers to set.
