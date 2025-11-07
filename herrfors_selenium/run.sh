#!/usr/bin/env bash
set -euo pipefail

# bashio functions are available in Home Assistant add-on environment
# If running outside HA for testing, emulate minimal behavior:
if command -v bashio >/dev/null 2>&1; then
  EMAIL=$(bashio::config 'email')
  PASSWORD=$(bashio::config 'password')
  TIMEZONE=$(bashio::config 'timezone')
  CHECK_INTERVAL=$(bashio::config 'check_interval')
  REFRESH_WINDOWS=$(bashio::config 'refresh_windows')
  USER_AGENT=$(bashio::config 'user_agent')
  RUN_IMMEDIATELY=$(bashio::config 'run_immediately_on_start')
else
  echo "bashio not found — running in test mode. Set env vars EMAIL/PASSWORD first."
  : "${EMAIL:?Need EMAIL env var}"
  : "${PASSWORD:?Need PASSWORD env var}"
  TIMEZONE="${TIMEZONE:-UTC}"
  CHECK_INTERVAL="${CHECK_INTERVAL:-300}"
  REFRESH_WINDOWS="${REFRESH_WINDOWS:-08:00-12:00}"
  USER_AGENT="${USER_AGENT:-Mozilla/5.0 (Windows NT 10.0; Win64; x64)}"
  RUN_IMMEDIATELY="${RUN_IMMEDIATELY:-true}"
fi

echo "🔌 Starting Home Assistant service endpoint..."
python3 /app/service.py &
SERVICE_PID=$!


# Normalize REFRESH_WINDOWS into a file /tmp/hf_windows.txt
WINDOWS_FILE="/tmp/hf_windows.txt"
printf "%s\n" "${REFRESH_WINDOWS[@]}" > "${WINDOWS_FILE}" 2>/dev/null || echo "${REFRESH_WINDOWS}" > "${WINDOWS_FILE}"

# Locations for triggers and token
REFRESH_TRIGGER_FILE="/share/herrfors_refresh_now"
TOKEN_FILE="/share/herrfors_token.json"

echo "🚀 Herrfors Selenium add-on starting..."
echo "📧 Using email: ${EMAIL}"
echo "⏱ Check interval: ${CHECK_INTERVAL}s, timezone: ${TIMEZONE}"
echo "🔁 Refresh windows:"
cat "${WINDOWS_FILE}" || true

# Export env for Python scripts
export HF_EMAIL="${EMAIL}"
export HF_PASSWORD="${PASSWORD}"
export HF_TIMEZONE="${TIMEZONE}"
export HF_USER_AGENT="${USER_AGENT}"
export HF_TOKEN_FILE="${TOKEN_FILE}"
export HF_REFRESH_TRIGGER_FILE="${REFRESH_TRIGGER_FILE}"

function run_fetch() {
    echo "🔄 Running fetch_and_save.py at $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    python3 /app/fetch_and_save.py || echo "⚠️ fetch script returned non-zero"
}

# Optionally run once on start
if [ "${RUN_IMMEDIATELY}" = "true" ] || [ "${RUN_IMMEDIATELY}" = "True" ]; then
    run_fetch
fi

# Main loop
while true; do
    # If refresh trigger file exists, perform immediate refresh
    if [ -f "${REFRESH_TRIGGER_FILE}" ]; then
        echo "📣 Manual refresh trigger detected. Running fetch..."
        run_fetch
        rm -f "${REFRESH_TRIGGER_FILE}"
        echo "✅ Manual refresh complete."
        sleep 1
        continue
    fi

    # Check schedule windows using Python helper (simpler in Python)
    python3 - <<PY
import os, sys, pytz
from datetime import datetime, time
tz = pytz.timezone(os.environ.get("HF_TIMEZONE", "UTC"))
now = datetime.now(tz).time()
windows = []
# read windows file (created above)
try:
    with open("${WINDOWS_FILE}", "r") as f:
        for ln in f:
            ln=ln.strip()
            if ln:
                windows.append(ln)
except Exception as e:
    print("Error loading windows:", e, file=sys.stderr)
    sys.exit(2)

def in_any_window(now, windows):
    for w in windows:
        try:
            start_s, end_s = w.split("-")
            start = time.fromisoformat(start_s)
            end = time.fromisoformat(end_s)
            if start <= end:
                if start <= now <= end:
                    return True
            else:
                # overnight window (e.g. 23:00-02:00)
                if now >= start or now <= end:
                    return True
        except Exception as e:
            print("Invalid window:", w, file=sys.stderr)
    return False

if in_any_window(now, windows):
    # signal to run parent shell to fetch by creating a marker file
    print("IN_WINDOW")
    sys.exit(0)
else:
    print("OUTSIDE_WINDOWS")
    sys.exit(1)
PY

    if [ $? -eq 0 ]; then
        echo "🕒 Current time is inside a refresh window. Running fetch..."
        run_fetch
    else
        echo "⏸ Current time outside windows. Next check in ${CHECK_INTERVAL}s"
    fi

    sleep "${CHECK_INTERVAL}"
done

##bashio::log.info "Copy config from ...."
##cp /data/config.yml /config/config.yml

##bashio::log.info "Starting ruuvibridge...."
##exec /usr/local/bin/ruuvibridge -config "$CONFIG_PATH"
