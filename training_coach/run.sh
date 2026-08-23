#!/usr/bin/with-contenv bashio
set -e

export TZ="$(bashio::config 'timezone')"
export RUN_TIME="$(bashio::config 'run_time')"
export OURA_WAIT_MINUTES="$(bashio::config 'oura_wait_minutes')"
export POLL_SECONDS="$(bashio::config 'poll_seconds')"
export NOTIFY_SERVICE="$(bashio::config 'notify_service')"
export RUN_IMMEDIATELY="$(bashio::config 'run_immediately_on_start')"
export STRAVA_ENTITY_PREFIX="$(bashio::config 'strava_entity_prefix')"
export WEEKLY_LONG_RUNS="$(bashio::config 'weekly_long_runs')"
export WEEKLY_QUALITY_RUNS="$(bashio::config 'weekly_quality_runs')"
export WEEKLY_STRENGTH="$(bashio::config 'weekly_strength')"
export WEEKLY_REST_DAYS="$(bashio::config 'weekly_rest_days')"
export LONG_RUN_MIN_MINUTES="$(bashio::config 'long_run_min_minutes')"
export DECISIONS_PATH="${DECISIONS_PATH:-/data/decisions.jsonl}"

bashio::log.info "Training Coach starting"
bashio::log.info "timezone=${TZ} run_time=${RUN_TIME} notify=${NOTIFY_SERVICE}"

exec python3 /app/main.py
