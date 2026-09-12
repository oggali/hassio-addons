#!/usr/bin/with-contenv bashio
set -e

export TZ="$(bashio::config 'timezone')"
export RUN_TIME="$(bashio::config 'run_time')"
export EVENING_TIME="$(bashio::config 'evening_time')"
export OURA_WAIT_MINUTES="$(bashio::config 'oura_wait_minutes')"
export POLL_SECONDS="$(bashio::config 'poll_seconds')"
export NOTIFY_SERVICE="$(bashio::config 'notify_service')"
export MOBILE_NOTIFY_SERVICE="$(bashio::config 'mobile_notify_service')"
export RUN_IMMEDIATELY="$(bashio::config 'run_immediately_on_start')"
export STRAVA_ENTITY_PREFIX="$(bashio::config 'strava_entity_prefix')"
export LONG_RUN_MIN_MINUTES="$(bashio::config 'long_run_min_minutes')"
export DB_PATH="${DB_PATH:-/data/coach.duckdb}"
export HISTORY_SEED_DAYS="${HISTORY_SEED_DAYS:-365}"

bashio::log.info "Training Coach starting"
bashio::log.info "timezone=${TZ} run_time=${RUN_TIME} evening=${EVENING_TIME} notify=${NOTIFY_SERVICE}"

exec python3 /app/main.py
