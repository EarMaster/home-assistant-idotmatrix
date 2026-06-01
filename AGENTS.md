# AGENTS.md

Codebase reference for AI agents working in this repository.

## What this is

A Home Assistant custom integration for iDotMatrix LED matrix displays (Bluetooth LE). It is installed via HACS and lives entirely under `custom_components/idotmatrix/`. There are no build steps — the integration runs inside a Home Assistant instance.

## Conventions

- **Conventional commits** — use `feat:`, `fix:`, `docs:`, `chore:`, `refactor:` prefixes. Group by type; only split if two changes of the same type are logically unrelated.
- **No PowerShell scripts** — use Bash or Python for any tooling.
- **Version bumps** — always update both `manifest.json` (`"version"`) and `CHANGELOG.md` together.
- **No custom services** — all control goes through entities (light, switch, text, select, button). Do not document or add `hass.services.async_register()` calls without a matching implementation.
- **Entity naming** — display names follow `Mode: Detail` convention so related entities sort together in the UI (e.g. `Clock: Style`, `Effect: Mode`, `Text: Message`, `Image: File`, `Image: Icon & Message`, `Chronograph: Start/Stop/Reset`). Entity IDs are derived from `entity_suffix` and are never renamed.
- **Entity categories** — settings-style entities carry `_attr_entity_category = EntityCategory.CONFIG` (imported from `homeassistant.const`), which places them in a separate "Configuration" section on the HA device page. Action buttons and the main mode/display controls have no category and appear in "Controls".

## Development workflow

**Releasing:** Use the `/release` skill (`.claude/commands/release.md`). It groups uncommitted changes into conventional commits, updates `manifest.json` version + `CHANGELOG.md`, tags, and pushes. GitHub Actions (`release.yml`) then creates the GitHub release automatically on tag push. HACS uses `hacs.json` for discovery.

**Smoke-testing without HA:** Run `python test_integration.py`. It mocks both `homeassistant.*` and `idotmatrix.*` via `sys.modules` before importing, so it works without a real HA instance or Bluetooth hardware.

## Architecture

### Central coordinator

`coordinator.py` — `IDotMatrixDataUpdateCoordinator` is the single source of truth. All platforms read state from it and write through its methods.

- **State dict** (`self._state`): `is_on`, `brightness` (0–255), `screen_flipped`, `current_mode` (`clock`/`text`/`effect`/`image`/`chronograph`/`scoreboard`), `clock_style`, `effect_mode`, `last_message`, `last_image`, `last_icon_message`, `scoreboard_home` (0–999), `scoreboard_away` (0–999). Platforms read this via `self.coordinator.data`.
- **BLE client**: `IDotMatrixClient(screen_size=ScreenSize[...], mac_address=...)` — persistent connection managed via `bleak-retry-connector`. On successful connect, `is_on` is set to `True` (the device has no readable on/off characteristic; connected = on).
- **Availability**: `_connected` flag toggled by `_ble_connect()` and the Bleak disconnected callback. Each state change schedules `async_request_refresh()` so entities update immediately. `_async_update_data` returns cached `_state` and retries `_ble_connect()` when not connected.
- **Command serialisation**: `_async_send_command` acquires an `asyncio.Lock` and `await`s the library call. No connect/disconnect per command — the persistent connection is reused.
- **Device events**: Methods fire `hass.bus.async_fire(f"{DOMAIN}_{event_type}", ...)` for device triggers (see `device_trigger.py`).

### Platform → coordinator method → library call

| Platform | Coordinator method | idotmatrix-api-client call |
|---|---|---|
| `light` | `async_turn_on/off` | `_client.common.turn_on/off` |
| `light` | `async_set_brightness(0–255)` | `_client.common.set_brightness(5–100)` |
| `switch` | `async_set_screen_flip(bool)` | `_client.common.set_screen_flipped` |
| `text` | `async_display_text(msg, size, color, speed)` | `_client.text.show_text` |
| `text` | `async_display_image(path_or_url)` | `_client.image.set_mode` + `upload_image_file` / `_client.gif.upload_gif_file` |
| `text` | `async_display_icon_message(icon, msg)` | renders composite GIF locally → `_client.gif.upload_gif_file` |
| `select` | `async_set_clock_mode(int)` | `_client.clock.show(style)` |
| `select` | `async_display_effect(int)` | `_client.effect.show(style, rgb_list)` |
| `button` | `async_sync_time()` | `_client.common.set_time(datetime)` |
| `button` | `async_start_chronograph()` | `_client.chronograph.start_from_zero` |
| `button` | `async_stop_chronograph()` | `_client.chronograph.pause` |
| `button` | `async_reset_chronograph()` | `_client.chronograph.reset` |
| `button` | `async_freeze_screen()` | `_client.common.freeze_screen` |
| `button` | `async_reset_device()` | `_client.common.reset` |
| `number` | `async_display_scoreboard(home, away)` | `_client.scoreboard.show(home, away)` |

Brightness conversion: HA uses 0–255, device uses 5–100%. Coordinator converts with `max(5, int(brightness / 255 * 100))`.

### Entity layout on the device page

**Controls** (no `entity_category`): Display (light), Display Mode (select), Chronograph: Reset/Start/Stop (buttons), Freeze Screen, Reset Device, Sync Time.

**Configuration** (`EntityCategory.CONFIG`): Clock: Style, Effect: Mode, Image: File, Image: Icon & Message, Screen Flip, Text: Message, Scoreboard: Home, Scoreboard: Away.

### Base entity

`entity.py` — `IDotMatrixEntity(CoordinatorEntity)`. All platform entities inherit from this. Sets `unique_id` as `{mac_address}_{entity_suffix}` and derives `available` from `coordinator.last_update_success`.

### Config flow

`config_flow.py` — Two entry paths:

1. **Auto-discovery** (`async_step_bluetooth`): HA's Bluetooth subsystem surfaces IDM- devices; flow shows a confirmation prompt.
2. **Manual** (`async_step_user` → `async_step_discovery` → optionally `async_step_manual`): queries `bluetooth.async_discovered_service_info` and shows a picker; a checkbox switches to manual MAC entry.

A **configure** step lets the user select the screen size (`CONF_SCREEN_SIZE`), which is stored in `entry.data` and passed to `IDotMatrixClient` at startup.

Options flow (`IDotMatrixOptionsFlowHandler`) exposes `scan_interval` (10–300 s), `connection_timeout` (5–120 s), and `retry_attempts` (1–10).

### Device triggers

`device_trigger.py` — Exposes HA device automation triggers by listening to custom bus events fired by the coordinator. Trigger types: `display_on`, `display_off`, `brightness_changed`, `mode_changed`, `text_displayed`, `effect_started`, `chronograph_started`, `chronograph_stopped`, `device_connected`, `device_disconnected`.

### Constants

```
DEFAULT_SCAN_INTERVAL = 30    # seconds between availability polls

Clock styles:  "RGB Swipe Outline"=0, "Christmas Tree"=1, "Checkers"=2, "Color"=3,
               "Hourglass"=4, "Alarm Clock"=5, "Outlines"=6, "RGB Corners"=7
Effect types:  "Horizontal Rainbow"=0, "Random Colored Pixels"=1,
               "White on Changing BG"=2, "Vertical Rainbow"=3,
               "Diagonal Right Rainbow"=4, "Diagonal Left Rainbow"=5, "Random Colored"=6
Color presets: red, green, blue, yellow, cyan, magenta, white, orange, purple, pink
Font sizes:    small=8, medium=12, large=16
```

### Library

`idotmatrix-api-client` by markusressel, installed from GitHub (see `manifest.json`). The library is write-only — there is no way to read device state back from the display.

### Key files

```
custom_components/idotmatrix/
  manifest.json        version, requirements, bluetooth filter (IDM-*)
  const.py             all constants, mappings (CLOCK_STYLES, EFFECT_TYPES, …)
  coordinator.py       IDotMatrixDataUpdateCoordinator — state, BLE comms
  entity.py            IDotMatrixEntity base class
  config_flow.py       setup wizard + options flow
  device_trigger.py    HA device automation triggers
  light.py             display on/off + brightness
  switch.py            screen flip (Configuration section)
  text.py              Text: Message, Image: File, Image: Icon & Message (Configuration section)
  select.py            Display Mode (Controls); Clock: Style, Effect: Mode (Configuration section)
  button.py            Chronograph: Start/Stop/Reset (Controls); Freeze Screen, Reset Device, Sync Time (Controls)
  number.py            Scoreboard: Home, Scoreboard: Away (Configuration section)
  services.yaml        service UI descriptions (no handlers registered — informational only)
  strings.json         config flow string keys
  translations/en.json English strings for config/options UI
test_integration.py    standalone smoke test (mocks HA + library)
```
