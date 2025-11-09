#!/usr/bin/with-contenv bashio
set -e

email=$(bashio::config 'email')
password=$(bashio::config 'password')
timezone=$(bashio::config 'timezone')
check_interval=$(bashio::config 'check_interval')
refresh_window_start=$(bashio::config 'refresh_window_start')
refresh_window_end=$(bashio::config 'refresh_window_end')
user_agent=$(bashio::config 'user_agent')
run_immediately=$(bashio::config 'run_immediately_on_start')


token_file="/share/herrfors_token.json"

export email
export password
export timezone
export user_agent
export token_file
export refresh_window_start
export refresh_window_end
export run_immediately

echo "🚀 herrfors selenium add-on starting..."
echo "📧 using email: ${email}"
echo "⏱ check interval: ${check_interval}s, timezone: ${timezone}"
echo "🔁 refresh windows: $(refresh_window_start) between $(refresh_window_end)"

# Start Python application
python3 /app/main.py
