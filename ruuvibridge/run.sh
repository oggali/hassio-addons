#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH="/data/config.yml"
bashio::log.info "Generating configuration for RuuviBridge..."

cat > "$CONFIG_PATH" <<EOF
gateway_polling:
  enabled: $(bashio::config 'gateway_polling_enabled')
  gateway_url: "$(bashio::config 'gateway_url')"
  bearer_token: "$(bashio::config 'gateway_bearer_token')"
  interval: $(bashio::config 'gateway_interval')

mqtt_listener:
  enabled: $(bashio::config 'mqtt_listener_enabled')
  broker_url: "$(bashio::config 'mqtt_listener_broker_url')"
  client_id: "$(bashio::config 'mqtt_listener_client_id')"
  username: "$(bashio::config 'mqtt_listener_username')"
  password: "$(bashio::config 'mqtt_listener_password')"
  topic_prefix: "$(bashio::config 'mqtt_listener_topic_prefix')"
  lwt_topic: "$(bashio::config 'mqtt_listener_lwt_topic')"
  lwt_online_payload: "$(bashio::config 'mqtt_listener_lwt_online_payload')"
  lwt_offline_payload: "$(bashio::config 'mqtt_listener_lwt_offline_payload')"

http_listener:
  enabled: $(bashio::config 'http_listener_enabled')
  port: $(bashio::config 'http_listener_port')

influxdb_publisher:
  enabled: $(bashio::config 'influxdb_enabled')
  url: "$(bashio::config 'influxdb_url')"
  auth_token: "$(bashio::config 'influxdb_auth_token')"
  org: "$(bashio::config 'influxdb_org')"
  bucket: "$(bashio::config 'influxdb_bucket')"
  measurement: "$(bashio::config 'influxdb_measurement')"

prometheus:
  enabled: $(bashio::config 'prometheus_enabled')
  port: $(bashio::config 'prometheus_port')
  measurement_metric_prefix: "$(bashio::config 'prometheus_prefix')"

mqtt_publisher:
  enabled: $(bashio::config 'mqtt_publisher_enabled')
  broker_url: "$(bashio::config 'mqtt_publisher_broker_url')"
  client_id: "$(bashio::config 'mqtt_publisher_client_id')"
  username: "$(bashio::config 'mqtt_publisher_username')"
  password: "$(bashio::config 'mqtt_publisher_password')"
  topic_prefix: "$(bashio::config 'mqtt_publisher_topic_prefix')"
  minimum_interval: $(bashio::config 'minimum_interval')
  publish_raw: $(bashio::config 'mqtt_publisher_publish_raw')
  lwt_topic: "$(bashio::config 'mqtt_publisher_lwt_topic')"
  lwt_online_payload: "$(bashio::config 'mqtt_publisher_lwt_online_payload')"
  lwt_offline_payload: "$(bashio::config 'mqtt_publisher_lwt_offline_payload')"
  homeassistant_discovery_prefix: $(bashio::config 'mqtt_publisher_homeassistant_discovery_prefix')

logging:
  type: "$(bashio::config 'log_type')"
  level: "$(bashio::config 'log_level')"
  timestamps: $(bashio::config 'log_timestamps')
  with_caller: $(bashio::config 'with_caller')

debug: $(bashio::config 'debug')
EOF
bashio::log.info "Copy config from ...."
cp /data/config.yml /config/config.yml

bashio::log.info "Starting ruuvibridge...."
exec /usr/local/bin/ruuvibridge -config "$CONFIG_PATH"
