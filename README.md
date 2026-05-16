# Plugit EV Charger - Home Assistant Integration

> ⚠️ **Disclaimer:** This is an unofficial integration and is not affiliated with, endorsed by, or connected to Plugit Oy. It uses a reverse-engineered private API that may change at any time without notice. Use at your own risk.

An unofficial Home Assistant custom component for Plugit EV charging network. Allows you to monitor and control your Plugit charger directly from Home Assistant.

## Features

- Start and stop charging (switch)
- Real-time power monitoring (W)
- Current per phase (L1, L2, L3)
- Session energy (kWh)
- Charging state (ongoing / idle)
- Automatic authentication and token renewal
- Auto-discovery of charger details on setup

## Requirements

- Home Assistant 2023.1 or newer
- Plugit user account
- A charger connected to the Plugit network

## Installation

### 1. Copy files

Copy the `plugit` folder to your Home Assistant `custom_components` directory:

```
/config/custom_components/plugit/
├── __init__.py
├── api.py
├── config_flow.py
├── const.py
├── coordinator.py
├── manifest.json
├── sensor.py
├── strings.json
├── switch.py
└── websocket.py
```

### 2. Restart Home Assistant

```
Settings → System → Restart
```

### 3. Add integration

1. Go to **Settings → Integrations → Add Integration**
2. Search for **Plugit**
3. Enter your Plugit account email and password
4. The integration will automatically discover your charger details

## Entities

| Entity | Type | Description |
|---|---|---|
| Plugit Charging | Switch | Start / stop charging session |
| Plugit Power | Sensor | Real-time power (W) |
| Plugit Current L1 | Sensor | Phase L1 current (A) |
| Plugit Current L2 | Sensor | Phase L2 current (A) |
| Plugit Current L3 | Sensor | Phase L3 current (A) |
| Plugit Session Energy | Sensor | Session energy (kWh) |
| Plugit State | Sensor | Charging state (ongoing/idle) |
| Plugit Charger Status | Sensor | OCPP status via WebSocket |

## Automation Examples

### Stop charging after reaching target energy

```yaml
automation:
  - alias: "Stop charging at 50 kWh"
    trigger:
      - platform: numeric_state
        entity_id: sensor.plugit_session_energy
        above: 50
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.plugit_charging
```

### Start charging when electricity is cheap

```yaml
automation:
  - alias: "Start charging when electricity price is low"
    trigger:
      - platform: numeric_state
        entity_id: sensor.nordpool_kwh_fi_eur_3
        below: 0.05
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.plugit_charging
```

## Technical Details

This integration uses the Plugit Cloud API discovered through reverse engineering of the official Android application. The API is not officially documented.

**API endpoints:**
- Authentication: `ory.plugitcloud.com` (Ory Identity)
- Data: `app-gw.plugitcloud.com`
- WebSocket: `socket.plugitcloud.com` (Socket.IO)

Data is refreshed every 30 seconds via REST API polling. A WebSocket connection provides real-time charger status updates.

## Known Limitations

- Only works with chargers connected to the Plugit network
- Multiple charger support is not yet implemented (uses the first charger on the account)
- WebSocket Status sensor may show Unknown if the connection cannot be established
- The private API may change at any time without notice

## Troubleshooting

**Integration not found in HA**
- Make sure all files are in `/config/custom_components/plugit/`
- Restart Home Assistant

**Authentication fails**
- Verify your email and password in the Plugit app
- Check your internet connection

**Sensors show Unknown**
- This is normal when no charging session is active
- Start a charging session and wait up to 30 seconds for data to appear

## License

MIT License - see [LICENSE](LICENSE) for details.
