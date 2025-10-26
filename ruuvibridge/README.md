# 🏷️ RuuviBridge Home Assistant Add-on

This add-on runs [RuuviBridge](https://github.com/Scrin/RuuviBridge) inside Home Assistant Supervised or OS installations.  
It bridges data from Ruuvi sensors (via Gateway, MQTT, or HTTP) to Home Assistant, InfluxDB, Prometheus, or MQTT brokers.

---

## 🧩 Features

- 🛰️ Collects RuuviTag data via:
  - Direct polling from a Ruuvi Gateway
  - Real-time MQTT updates
  - HTTP POSTs from Ruuvi Gateway
- 📦 Publishes data to:
  - Home Assistant (via MQTT Discovery)
  - InfluxDB (1.8, 2.x, or 3.x)
  - Prometheus
- ⚙️ Fully configurable through the add-on UI
- 🧠 Supports extended values, filtering, and debug logging

---

## ⚙️ Configuration

All options are available in the add-on UI and written automatically to `/data/config.yml` before startup.

### 🌐 Gateway Polling
| Option | Description | Default |
|--------|--------------|----------|
| `gateway_polling_enabled` | Enable direct polling from a Ruuvi Gateway | `false` |
| `gateway_url` | Gateway API URL | `http://ip.or.hostname.of.the.gateway` |
| `gateway_bearer_token` | Optional API key for authenticated access | `""` |
| `gateway_interval` | Polling interval (Go duration format) | `10s` |

### ☁️ MQTT Listener
| Option | Description | Default |
|--------|--------------|----------|
| `mqtt_listener_enabled` | Enable subscribing to MQTT | `false` |
| `mqtt_listener_broker_url` | Broker URL (e.g. `tcp://core-mosquitto:1883`) | `tcp://ip.or.hostname:1883` |
| `mqtt_listener_client_id` | MQTT client ID | `RuuviBridgeListener` |
| `mqtt_listener_username` | Username | `ruuvibridge` |
| `mqtt_listener_password` | Password | `ruuvipassword` |
| `mqtt_listener_topic_prefix` | Topic prefix (wildcards supported) | `ruuvi` |
| `mqtt_listener_lwt_topic` | LWT topic | `""` |
| `mqtt_listener_lwt_online_payload` | Payload when online | `{"state":"online"}` |
| `mqtt_listener_lwt_offline_payload` | Payload when offline | `{"state":"offline"}` |

---

### 🌐 HTTP Listener
| Option | Description | Default |
|--------|--------------|----------|
| `http_listener_enabled` | Enable HTTP listener | `false` |
| `http_listener_port` | HTTP port | `8080` |

---

### 🧮 InfluxDB Publisher
| Option | Description | Default |
|--------|--------------|----------|
| `influxdb_enabled` | Enable InfluxDB publishing | `false` |
| `influxdb_url` | InfluxDB URL | `http://localhost:8086` |
| `influxdb_auth_token` | Auth token or `user:pass` (v1.8) | `changethis` |
| `influxdb_org` | Organization (v2+) | `""` |
| `influxdb_bucket` | Bucket/database | `ruuvi` |
| `influxdb_measurement` | Measurement name | `ruuvi_measurements` |

---

### 📊 Prometheus Exporter
| Option | Description | Default |
|--------|--------------|----------|
| `prometheus_enabled` | Enable Prometheus | `false` |
| `prometheus_port` | Port | `8081` |
| `prometheus_prefix` | Metric prefix | `ruuvi` |

---

### 📤 MQTT Publisher
| Option | Description | Default |
|--------|--------------|----------|
| `mqtt_publisher_enabled` | Enable publishing to MQTT | `false` |
| `mqtt_publisher_broker_url` | MQTT broker URL | `tcp://ip.or.hostname:1883` |
| `mqtt_publisher_client_id` | Client ID | `RuuviBridgePublisher` |
| `mqtt_publisher_username` | Username | `ruuvibridge` |
| `mqtt_publisher_password` | Password | `ruuvipassword` |
| `mqtt_publisher_topic_prefix` | Publish topic prefix | `ruuvibridge` |
| `mqtt_publisher_publish_raw` | Publish raw value topics | `false` |
| `mqtt_publisher_lwt_topic` | LWT topic | `""` |
| `mqtt_publisher_lwt_online_payload` | Online payload | `{"state":"online"}` |
| `mqtt_publisher_lwt_offline_payload` | Offline payload | `{"state":"offline"}` |
| `mqtt_publisher_homeassistant_discovery_prefix` | HA MQTT discovery prefix | `homeassistant` |

---

### 🪵 Logging & Debug
| Option | Description | Default |
|--------|--------------|----------|
| `log_type` | `structured` or `json` | `structured` |
| `log_level` | Logging level | `info` |
| `log_timestamps` | Include timestamps | `true` |
| `debug` | Enable debug mode | `false` |

---

## 🚀 Installation

1. In Home Assistant → **Settings → Add-ons → Add-on Store**
2. Click “⋮” → **Repositories**
3. Add: