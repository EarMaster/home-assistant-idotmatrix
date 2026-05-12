# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Home Assistant custom integration for iDotMatrix LED displays (Bluetooth, device names starting with `IDM-`). It wraps the [`idotmatrix`](https://github.com/markusressel/idotmatrix-api-client) Python library (≥0.1.0) and exposes HA entities for display control.

## Running Tests

```bash
# Run the standalone test script (mocks HA + idotmatrix library internally)
python test_integration.py
```

There is no test framework (pytest/unittest runner) configured. `test_integration.py` mocks both `homeassistant.*` and `idotmatrix.*` via `sys.modules` before importing, so it runs without a real HA instance or Bluetooth hardware.

## Architecture

The integration follows the standard HA coordinator pattern:

```
ConfigEntry (MAC address + device name + screen_size)
    └── IDotMatrixDataUpdateCoordinator  (coordinator.py)
            ├── Holds IDotMatrixClient with persistent BLE connection + auto-reconnect
            ├── ConnectionListener callbacks update self._connected for availability tracking
            ├── Holds device state dict (no read-back from device — state is tracked locally)
            ├── _async_send_command() serializes all writes via asyncio.Lock
            └── Fires HA bus events on state changes (e.g. idotmatrix_display_on)
                
IDotMatrixEntity  (entity.py)
    └── CoordinatorEntity base — all platform entities inherit from this
            ├── IDotMatrixLight      (light.py)   — brightness control
            ├── IDotMatrixSwitch     (switch.py)  — screen flip
            ├── IDotMatrixText       (text.py)    — send text messages
            ├── IDotMatrixSelect     (select.py)  — clock style + effect mode
            └── IDotMatrix*Button    (button.py)  — reset, freeze, chronograph, sync time
```

**Key design detail**: The `idotmatrix` library is write-only — there is no way to read device state. All state in `coordinator._state` is maintained locally after writes. The library maintains a persistent BLE connection with built-in auto-reconnect (5 s retry loop).

**Connection availability**: `coordinator._connected` is updated via `ConnectionListener` callbacks (`_on_connected` / `_on_disconnected`). Each callback schedules an `async_request_refresh()` so entities update availability immediately.

## Key Files

- `custom_components/idotmatrix/const.py` — all constants: `CLOCK_STYLES`, `EFFECT_TYPES`, `FONT_SIZES`, `COLOR_PRESETS`, service names
- `custom_components/idotmatrix/coordinator.py` — Bluetooth connection lifecycle, all device command methods
- `custom_components/idotmatrix/config_flow.py` — UI config flow: auto-discovery (BT scan) or manual MAC entry; configure step for screen_size; options flow for scan interval
- `custom_components/idotmatrix/services.yaml` — service definitions consumed by HA UI
- `custom_components/idotmatrix/strings.json` — UI strings for config flow steps

## Releases

Releases are triggered by pushing a `v*` tag. GitHub Actions (`.github/workflows/release.yml`) zips `custom_components/idotmatrix/` and creates a GitHub Release with the zip attached. HACS uses `hacs.json` to discover the integration.

## HA Integration Conventions

- All async methods are prefixed `async_` per HA convention
- Platform setup entry points are `async_setup_entry(hass, config_entry, async_add_entities)`
- `manifest.json` declares `"iot_class": "local_polling"` and `"bluetooth": [{"local_name": "IDM-*"}]`
- Unique ID for each config entry is the device MAC address (prevents duplicates)
- Brightness conversion: HA uses 0–255, device uses 5–100% — coordinator converts in `async_set_brightness` with `max(5, int(brightness / 255 * 100))`
- Screen size is stored in `entry.data[CONF_SCREEN_SIZE]` and passed to `IDotMatrixClient` constructor
