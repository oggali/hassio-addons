# Hass.io add-ons

Private Home Assistant add-on repository. Maintainer `@oggali`.

Add it in Home Assistant under **Settings → Add-ons → Add-on Store → ⋮ → Repositories**:

```text
https://github.com/oggali/hassio-addons
```

Each top-level directory with a `config.yaml` is one add-on. They do not share an image or a runtime. Behavior and options live in that add-on's own README.

| Add-on | What it does |
|---|---|
| [Training Coach](training_coach/README.md) | Morning and evening running plan from Oura, Garmin, and Strava, with Telegram and optional Android check-in. Rule detail is in [training_coach/docs](training_coach/docs/sessions.md). |
| [RuuviBridge](ruuvibridge/README.md) | Runs upstream [RuuviBridge](https://github.com/Scrin/RuuviBridge) and publishes RuuviTag data. |
| [Herrfors](herrfors_selenium/README.md) | Headless Chromium login that refreshes a Herrfors session token for consumption queries. |

Releases are git tags per add-on, for example `training_coach/2026.10.24`. Edit and CI rules are in [AGENTS.md](AGENTS.md).
