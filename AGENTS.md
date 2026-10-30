# Hass.io add-ons

Private Home Assistant add-on repository (`repository.yaml`, maintainer `@oggali`). Each top-level directory that contains `config.yaml` is one add-on. They do not share a Python package, image, or runtime.

The GitHub landing page is `README.md`. Keep it a catalog: one line per add-on, the store URL, and a pointer here. Add-on behavior stays in that add-on's `README.md`. Training Coach rule detail stays in `training_coach/docs/`.

| Directory | What it is | Tests |
|---|---|---|
| `training_coach/` | Morning/evening running coach. Python app under `app/`, DuckDB, HA API. Read `training_coach/AGENTS.md` before editing it. | `training_coach/tests/` |
| `ruuvibridge/` | Thin wrapper around the upstream [RuuviBridge](https://github.com/Scrin/RuuviBridge) binary. Config is rendered to `/data/config.yml` by `run.sh`. | none |
| `herrfors_selenium/` | Headless Chromium login that refreshes a Herrfors session token. Python under `app/` (`main.py`, `herrfors_session.py`, `refresh_server.py`, `decode_encode_token.py`). | none |
| `.github/` | Opens a pull request on `feature/` `fix/` `refactor/` pushes, then the PR gate and post-merge tagging. `scripts/addon_ci.py` discovers add-ons, checks versions, runs tests, tags releases. | `scripts/test_addon_ci.py` |

`ruuvibridge/.github/workflows/build.yml` builds that add-on image on its own. New add-ons do not copy that workflow. Releases for this repo are git tags from `.github/workflows/addon-tag.yml`.

## Version and CI

Any file under an add-on directory counts as a change to that add-on, including README and this kind of agent note.

A push to `feature/**`, `fix/**`, or `refactor/**` runs `addon-pr.yml`. It opens a pull request to `main` when none is open, and enables auto-merge as a merge commit. Later pushes to that branch update the same pull request.

On a pull request to `main`:

1. `addon-ci.yml` runs `python3 .github/scripts/test_addon_ci.py -v`, then `addon_ci.py check`, then `addon_ci.py test`.
2. `check` requires the add-on's `version` in `config.yaml` to differ from `main`, and the tag `<dirname>/<version>` to be unused. Example tags: `training_coach/2026.10.06`, `ruuvibridge/2026.10.05.1`.
3. `test` creates a venv and runs `unittest discover` only for changed add-ons that have a `tests/` directory.
4. After the PR is merged, `addon-tag.yml` tags that version and opens a GitHub Release. The release notes are the PR title and body.

Version strings are calendar dates: `YYYY.MM.DD` for the first release that day, `YYYY.MM.DD.N` when a later release is needed the same day (`N` starts at `1`). Bump `version` in the same change as the add-on edit. Leave other add-ons' versions alone.

## Commits and pull requests

The skill `git-commit-pr` creates the branch and writes the conventional commit. Push that branch and stop. `addon-pr.yml` opens the pull request. Do not open a second one with `gh`. In this repo:

- One add-on per branch, unless the change is the shared CI scripts. The commit includes the add-on edit, that add-on's `version` bump in `config.yaml`, and the README, `docs/`, or `AGENTS.md` update when behavior, entities, stdin commands, config keys, layout, or decision rules change.
- `scope` is the area inside the add-on, such as `notification` or `session`. Shared CI scripts use `ops(ci)`. The commit type does not change the calendar `version`.
- `addon-pr.yml` titles the pull request with the first commit subject on the branch and uses the commit log as the body. Those become the GitHub Release notes, so write the commits for someone reading the release.
- Do not commit `__pycache__`, virtualenvs, `.env`, DuckDB files, or `herrfors_selenium/tmp_tests/`.
- Auto-merge must stay a merge commit so `addon-tag.yml` receives `merge_commit_sha`. After that merge, the workflow tags `<dirname>/<version>` and opens the GitHub Release.

## How to work here

- Change one add-on per PR unless the task is the shared CI scripts.
- Keep add-on options in that add-on's `config.yaml` (`options` and `schema`). `run.sh` is what turns those options into the process environment.
- User-facing overview belongs in the add-on's `README.md`. Training Coach rule detail lives in `training_coach/docs/` and is linked from that README. Update the page that owns the rule when behavior, entities, stdin commands, or config keys change.
- If the add-on has `AGENTS.md`, update it in the same change when layout, decision rules, schema, or its docs change. That file should say so itself.
- Defaults in `config.yaml` are this install (Telegram service, Strava entity prefix, Herrfors credentials fields, Ruuvi broker examples). Leave them unless the task is to change them.
- Tests are `unittest`, not pytest. From the repo root:

```bash
python3 -m unittest discover -s training_coach/tests -v
python3 .github/scripts/test_addon_ci.py -v
```

- `training_coach` tests need `duckdb`, `requests`, and `websocket-client` (`training_coach/app/requirements.txt`). CI installs that file into a fresh venv; locally, install it yourself if imports fail.
- Do not add a shared library between add-ons. Copy a helper only if both sides truly need it, and say so in the PR.
