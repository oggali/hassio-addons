#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "Generating configuration for RuuviBridge..."

CONFIG_PATH="/data/config.yml"

cat > "$CONFIG_PATH" <<EOF
log_level: $(bashio::config 'log_level')

mqtt:
  host: $(bashio::config 'mqtt_host')
  port: $(bashio::config 'mqtt_port')
  username: $(bashio::config 'mqtt_username')
  password: $(bashio::config 'mqtt_password')

homeassistant_discovery_prefix: $(bashio::config 'homeassistant_discovery_prefix')

sources:
  - type: ruuvitag_mqtt

sinks:
  - type: mqtt_homeassistant
    topic_prefix: $(bashio::config 'homeassistant_discovery_prefix')
EOF

bashio::log.info "Starting RuuviBridge..."
exec /usr/local/bin/RuuviBridge -config "$CONFIG_PATH"
