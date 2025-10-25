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
| `mqtt_listener_enabled` | Enable subscribing to MQTT updates | `false` |
| `mqtt_listener_broker_url` | Broker URL (e.g. `tcp://core-mosquitto:1883`) | `tcp://ip.or.hostname:1883` |
| `mqtt_listener_client_id` | MQTT client ID | `RuuviBridgeListener` |
| `mqtt_listener_username` | MQTT username | `ruuvibridge` |
| `mqtt_listener_password` | MQTT password | `ruuvipassword` |
| `mqtt_listener_topic_prefix` | Topic prefix (supports wildcards) | `ruuvi` |

### 🌐 HTTP Listener
| Option | Description | Default |
|--------|--------------|----------|
| `http_listener_enabled` | Enable HTTP listener for Gateway POSTs | `false` |
| `http_listener_port` | Port to listen on | `8080` |

### 🧮 InfluxDB Publisher
| Option | Description | Default |
|--------|--------------|----------|
| `influxdb_enabled` | Enable publishing to InfluxDB | `false` |
| `influxdb_url` | InfluxDB server URL | `http://localhost:8086` |
| `influxdb_auth_token` | Auth token or `username:password` for InfluxDB 1.8 | `changethis` |
| `influxdb_org` | Organization (for InfluxDB 2.x) | `""` |
| `influxdb_bucket` | Bucket or database | `ruuvi` |
| `influxdb_measurement` | Measurement name | `ruuvi_measurements` |

### 📊 Prometheus Exporter
| Option | Description | Default |
|--------|--------------|----------|
| `prometheus_enabled` | Enable Prometheus metrics | `false` |
| `prometheus_port` | Listen port | `8081` |
| `prometheus_prefix` | Metric prefix | `ruuvi` |

### 📤 MQTT Publisher
| Option | Description | Default |
|--------|--------------|----------|
| `mqtt_publisher_enabled` | Enable publishing to MQTT | `false` |
| `mqtt_publisher_broker_url` | MQTT broker URL | `tcp://ip.or.hostname:1883` |
| `mqtt_publisher_client_id` | MQTT client ID | `RuuviBridgePublisher` |
| `mqtt_publisher_username` | Username | `ruuvibridge` |
| `mqtt_publisher_password` | Password | `ruuvipassword` |
| `mqtt_publisher_topic_prefix` | Topic prefix | `ruuvibridge` |

### 🪵 Logging & Debug
| Option | Description | Default |
|--------|--------------|----------|
| `log_type` | Log output format (`structured` or `json`) | `structured` |
| `log_level` | Verbosity (`trace`, `debug`, `info`, `warn`, `error`, `fatal`, `panic`) | `info` |
| `log_timestamps` | Include timestamps in logs | `true` |
| `debug` | Enable verbose debugging | `false` |

---

## 🚀 Usage

1. Add this repository to your Home Assistant add-on store:  
