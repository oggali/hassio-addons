# RuuviBridge Home Assistant Add-on

This add-on runs [RuuviBridge](https://github.com/Scrin/RuuviBridge) inside Home Assistant.

It collects data from RuuviTags and publishes them to Home Assistant via MQTT Discovery.

## Configuration

| Option | Description | Default |
|--------|--------------|----------|
| `mqtt_host` | MQTT broker URL | `mqtt://core-mosquitto` |
| `mqtt_port` | MQTT port | `1883` |
| `mqtt_username` | MQTT username | *(optional)* |
| `mqtt_password` | MQTT password | *(optional)* |
| `homeassistant_discovery_prefix` | MQTT discovery prefix | `homeassistant` |
| `log_level` | Logging level | `info` |

## Usage

1. Add this repo to Home Assistant add-on store (Repository URL: `https://github.com/oggali/hassio-addons`).
2. Install the “RuuviBridge” add-on.
3. Configure MQTT and start it.
4. Sensors appear automatically via MQTT discovery.
