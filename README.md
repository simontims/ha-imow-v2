# ha-imow-v2 — STIHL iMow Gen5+ for Home Assistant

A native Home Assistant custom integration for **STIHL iMow Gen5+ mowers** (including Evo variants) that do not work with the original [stihl_imow](https://www.home-assistant.io/integrations/stihl_imow/) integration.

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

---

## Features

- **Live updates:** state changes arrive within seconds over STIHL's push channel (the same one the myimow web app uses); polling is only a safety net
- Status: activity (mowing, returning, docked, charging, paused, error…), job zone, time remaining, battery, rain, docked, online
- Errors with STIHL's own text (`sensor.<mower>_error_message`, in Home Assistant's language where STIHL has a translation)
- GPS position on the map, updated while the mower is away from the dock (interval configurable)
- Lawn mower entity with Start / Pause / Dock, plus a service for zone and duration
- Statistics: operating time, distance, blade time, number of jobs
- Diagnostics download with personal data removed
- Sign-in, re-authentication and reconfigure through the Home Assistant UI

## Supported Mowers

All STIHL iMow models on the **Gen5+ platform** (myimow.stihl.com):

- iMow® 5 / iMow® 5 EVO
- iMow® 6 / iMow® 6 EVO ✅ *(tested)*
- iMow® 7 / iMow® 7 EVO

Other Gen5+ models should work but are untested.

> Legacy models using `oauth2.imow.stihl.com` are **not** supported.

---

## Installation via HACS

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations → Custom repositories**.
3. Add this repository as an **Integration**.
4. Search for **STIHL iMow v2** and click **Install**.
5. Restart Home Assistant.

## Manual Installation

```
custom_components/imow_v2/  →  config/custom_components/imow_v2/
```

Restart Home Assistant.

Requires Home Assistant 2025.8 or newer.

---

## Configuration

### Adding the integration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **STIHL iMow v2**.
3. Sign in with the email address and password you use in the iMow app or on myimow.stihl.com.
4. Each mower on the account appears as a device.

Each STIHL account can be added once. The entry is tied to the account itself, so changing the account's email address later doesn't break it.

### If the password changes

If STIHL stops accepting the saved password, Home Assistant shows a **Re-authenticate** notice under **Settings → Devices & services**. Enter the new password there; nothing else needs setting up again.

### Changing the email address or password

Open the integration, use the **⋮** menu → **Reconfigure**, and enter the new details. They must belong to the same STIHL account; to use a different account, add the integration again.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| Poll interval | 10 min | How often to fetch the full status. Live changes arrive anyway. |
| GPS tracking interval | 60 s | How often to update the position while the mower is away from the dock. 0 turns tracking off. |

Saving the options reloads the integration.

---

## Entities

Entity IDs come from the mower's name in the STIHL app. For a mower named **"Robin"** you get `sensor.robin_battery` and so on; `<mower>` below stands for that name.

### Lawn mower
`lawn_mower.<mower>`: Start (resumes when paused, otherwise starts a manual job for the Default Mowing Duration), Pause, Dock.

> **Start doesn't choose a zone.** The mower decides where to begin. To pick a zone, use the `imow_v2.intent` service below.

### Sensors
| Entity | Description |
|--------|-------------|
| `sensor.<mower>_activity` | docked, charging, driving, mowing, returning, paused, error, locked, offline, sleeping, busy |
| `sensor.<mower>_overall_state` / `_job_state` | Raw states from STIHL |
| `sensor.<mower>_job_zone` | Zone of the running manual job |
| `sensor.<mower>_time_remaining` | Minutes left in the current job |
| `sensor.<mower>_job_start_time` / `_job_end_time` | Current job times |
| `sensor.<mower>_error_message` | Active errors in words |
| `sensor.<mower>_battery` | Battery level |
| `sensor.<mower>_charge_sufficient_for` | Whether the battery is enough to mow or only to return to the dock |
| `sensor.<mower>_battery_next_state` / `_battery_next_state_time` | STIHL's forecast of the next battery state |
| `sensor.<mower>_current_area` | Current area |
| `sensor.<mower>_last_event` / `_last_event_time` | Latest entry in the mower's event log |
| `sensor.<mower>_advice` | Advice shown in the STIHL app |
| `sensor.<mower>_cutting_height` | Cutting height |
| `sensor.<mower>_last_seen` | Last contact with the STIHL cloud |
| Diagnostic | GPS accuracy and update time, Wi-Fi and cellular signal, cellular network |
| Statistics | Total operating time, total distance, blade operating time, total mowing jobs |

### Binary sensors
Rain sensor, Online, Docked, Error, Service required, Mowing plan active, Wi-Fi connected, Cellular connected, Software update available.

### Other
| Entity | Description |
|--------|-------------|
| `device_tracker.<mower>_location` | GPS position on the map |
| `number.<mower>_default_mowing_duration` | Duration used by Start (minutes) |
| `button.<mower>_refresh_status` | Ask the mower to report its state now |
| `button.<mower>_clear_errors` | Clear errors (once the cause is fixed) |

---

## Services

### `imow_v2.intent`

Send a command to a mower.

| Field | Required | Description |
|-------|----------|-------------|
| `action` | yes | `start-mowing`, `pause`, `resume`, `end-job-and-return-to-dock`, `clear-errors`, `force-status-update` |
| `mower_device` | one of | Device (picked in the UI) |
| `mower_name` | one of | Mower name |
| `duration` | no | Minutes to mow (`start-mowing` only; defaults to the Default Mowing Duration) |
| `zone` | no | Zone number to start in (`start-mowing` only; 0 starts from the dock) |

Example: mow zone 1 for an hour.

```yaml
action: imow_v2.intent
data:
  action: start-mowing
  mower_name: Robin
  zone: 1
  duration: 60
```

---

## Troubleshooting

Under **Settings → Devices & services → STIHL iMow v2 → ⋮ → Download diagnostics** you get a file to attach to an issue. The email address, password, tokens, serial numbers, IMEI/IMSI, MAC and IP addresses, Wi-Fi names and GPS positions are removed from it.

---

## Disclaimer

This is an unofficial integration. It is not made, endorsed or supported by STIHL. "STIHL" and "iMow" are trademarks of their owner.

## Credits

Authentication and API reverse-engineering based on the excellent work of **TA2k** in [ioBroker.iMow](https://github.com/TA2k/ioBroker.iMow).
Modifications and Python port by [aquarius72](https://github.com/aquarius72).

## License

MIT — see [LICENSE](LICENSE)
