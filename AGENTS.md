# AGENTS.md

Codebase reference for AI agents working in this repository.

## What this is

A Home Assistant custom integration for iDotMatrix LED matrix displays (Bluetooth LE). It is installed via HACS and lives entirely under `custom_components/idotmatrix/`. There are no build steps — the integration runs inside a Home Assistant instance.

## Conventions

- **Conventional commits** — use `feat:`, `fix:`, `docs:`, `chore:`, `refactor:` prefixes. Group by type; only split if two changes of the same type are logically unrelated.
- **No PowerShell scripts** — use Bash or Python for any tooling.
- **Version bumps** — always update both `manifest.json` (`"version"`) and `CHANGELOG.md` together.
- **Entities first, actions sparingly** — control goes through entities (light, switch, text, select, button). Actions live in `services.py` (`show_icon_message`, `show_text`, `start_countdown`, `set_scoreboard`) and exist only for what entities can't offer: pickers (icon, color, duration), several settings in one call, and `restore_after`. Every action uses a `target:` (device/entity/area — a field named `device_id` would be hidden by the action editor), keeps names/descriptions in `strings.json` + `translations/{en,de}.json` (not in `services.yaml`), and must have a matching `async_register()`.
- **Entity naming** — display names follow `Mode: Detail` convention so related entities sort together in the UI (e.g. `Clock: Style`, `Effect: Mode`, `Text: Message`, `Image: File`, `Icon & Message: Text`, `Chronograph: Start/Stop/Reset`). Entity IDs are derived from `entity_suffix` and are never renamed.
- **Entity categories** — settings-style entities carry `_attr_entity_category = EntityCategory.CONFIG` (imported from `homeassistant.const`), which places them in a separate "Configuration" section on the HA device page. Action buttons and the main mode/display controls have no category and appear in "Controls".

## Development workflow

**Releasing:** Use the `/release` skill (`.claude/commands/release.md`). It groups uncommitted changes into conventional commits, updates `manifest.json` version + `CHANGELOG.md`, tags, and pushes. GitHub Actions (`release.yml`) then creates the GitHub release automatically on tag push. HACS uses `hacs.json` for discovery.

**Smoke-testing without HA:** Run `python test_integration.py`. It mocks both `homeassistant.*` and `idotmatrix.*` via `sys.modules` before importing, so it works without a real HA instance or Bluetooth hardware.

## Architecture

### Central coordinator

`coordinator.py` — `IDotMatrixDataUpdateCoordinator` is the single source of truth. All platforms read state from it and write through its methods.

- **State dict** (`self._state`): `is_on`, `brightness` (0–255), `screen_flipped`, `current_mode` (`clock`/`text`/`effect`/`image`/`chronograph`/`scoreboard`), `clock_style`, `effect_mode`, `last_message`, `text_color`/`text_font_size`/`text_speed` (last show_text settings), `last_image`, `icon_message_icon`, `icon_message_text`, `last_image_kind` (`file`/`icon_message` — which one Display Mode → image re-sends), `icon_message_text_color`, `icon_message_icon_color` (`[r, g, b]` lists; preset names from 1.7.5–1.8.0 are migrated on load), `scoreboard_home` (0–999), `scoreboard_away` (0–999). Platforms read this via `self.coordinator.data`.
- **BLE client**: `IDotMatrixClient(screen_size=ScreenSize[...], mac_address=..., transport_factory=self._create_transport, install_signal_handlers=False)` from `idotmatrix-api-client` (pinned to an exact PyPI version in `manifest.json` — never an unpinned git URL: HA reinstalls URL requirements on every restart). `_create_transport` returns a `BleakTransport` subclass that connects with `bleak-retry-connector`'s `establish_connection` (works through ESPHome BT proxies) and downgrades writes with response to paced write-without-response if the write characteristic lacks the `write` property. `_ble_connect()` hands HA's current `BLEDevice` to `set_ble_device()` and calls `connect()`; the library subscribes to notifications itself. On successful connect, `is_on` is set to `True` (the device has no readable on/off characteristic; connected = on) and the time is synced.
- **Availability**: `_connected` flag set by `_ble_connect()` and cleared by the library's disconnect listener (`_async_on_disconnected`). The library's own `is_connected()` stays true after a link dies silently, so `_link_up()` checks the transport instead; `_async_send_command` resets the connection (`_async_reset_connection`) and reconnects when it is down. Each state change schedules `async_request_refresh()` so entities update immediately. `_async_update_data` returns cached `_state` and retries `_ble_connect()` when not connected.
- **Command serialisation**: `_async_send_command` acquires an `asyncio.Lock` and `await`s the library call. No connect/disconnect per command — the persistent connection is reused.
- **Temporary content (`restore_after`)**: every content change goes through `_set_current_mode()`, which bumps `_content_generation`. `snapshot_for_restore()` captures the mode plus `_RESTORE_KEYS`; `schedule_restore()` only fires if the generation is unchanged (nothing else shown meanwhile). A still-pending snapshot is reused, so chained notifications return to the original screen. `async_activate_mode()` re-shows a mode (shared with the Display Mode select).
- **Display Preview** (`image.py`, `preview.py`): the device is write-only, so the preview is derived. Exact pixels are captured at send time into `_captured_preview = (content_generation, native_gif)` (Icon & Message GIF, `_adapt_image()` output for files). `async_update_preview()` runs in `_async_update_data` and re-renders only when `(content_generation, is_on, minute-if-clock)` changes: captured pixels if the generation matches, otherwise rebuilt from state (text via the library's glyph drawing, device-drawn modes via `preview.fallback_spec()` + the Icon & Message renderer). `preview_version` changes only when the bytes change; the entity upscales with NEAREST (~320 px) and caches per version. Per-size reference templates for device-drawn modes are meant to replace `fallback_spec()` later.
- **GIF upload**: `_send_gif_blocks` uploads ready, canvas-sized GIF bytes with the library's `create_gif_data_packets` (`INDEX_SHOW_NOW`) + `ConnectionManager.send_packets(response=True, wait_for_ack=True)`: the device acknowledges each 4 KB block (`05 00 01 00 xx` on `fa03`) before the next is sent. It skips the conversion of the library's `upload_gif_file`, so the Display Preview captures exactly the uploaded bytes; files are normalised beforehand in `_adapt_image` (library `_load_gif_and_adapt_to_canvas`). Static images go through `image.set_mode` + `image.upload_image_file(BytesIO)`.
- **Animated icons** (`animation.py`): `lam:<id>` sources are fetched by `_fetch_image_data` from LaMetric's public icon endpoint and cached in `.storage/idotmatrix_lametric/`. Full screen they bypass the library's GIF normalisation (`_adapt_image(pixel_art=True)` → `fullscreen_gif`, integer NEAREST upscale). Icon & Message treats icon frames and text scroll positions as timelines; `combine()` makes the GIF loop a whole number of icon loops and text loops (the text pauses absorb the difference), then `prune()` drops the shortest frames until ≤64.
- **Device events**: Methods fire `hass.bus.async_fire(f"{DOMAIN}_{event_type}", ...)` for device triggers (see `device_trigger.py`).

### Platform → coordinator method → library call

| Platform | Coordinator method | idotmatrix-api-client call |
|---|---|---|
| `light` | `async_turn_on/off` | `_client.common.turn_on/off` |
| `light` | `async_set_brightness(0–255)` | `_client.common.set_brightness(5–100)` |
| `switch` | `async_set_screen_flip(bool)` | `_client.common.set_screen_flipped` |
| `text` | `async_display_text(msg, size, color, speed)` | `_client.text.show_text` |
| `text` | `async_display_image(path_or_url)` | `_client.image.set_mode` + `upload_image_file` / `_send_gif_blocks` (see below) |
| `text` / `select` / action | `async_update_icon_message(display=…, icon=…, text=…, text_color=…, icon_color=…)` → `async_display_icon_message()` (uses stored settings) | renders composite GIF locally (static if the text fits, ping-pong scroll otherwise, ≤64 frames) → `_send_gif_blocks` (skips the library's normalisation and its 2 s animation cap) |
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

**Configuration** (`EntityCategory.CONFIG`): Clock: Style, Effect: Mode, Image: File, Icon & Message: Icon, Icon & Message: Text, Icon & Message: Text Color, Icon & Message: Icon Color, Screen Flip, Text: Message, Scoreboard: Home, Scoreboard: Away.

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
  text.py              Text: Message, Image: File, Icon & Message: Icon/Text (Configuration section)
  select.py            Display Mode (Controls); Clock: Style, Effect: Mode (Configuration section)
  button.py            Chronograph: Start/Stop/Reset (Controls); Freeze Screen, Reset Device, Sync Time (Controls)
  number.py            Scoreboard: Home, Scoreboard: Away (Configuration section)
  services.py          actions + target resolution + restore_after
  image.py             Display Preview image entity
  preview.py           preview rendering (upscale, text approximation, fallbacks)
  animation.py         LaMetric icons (lam:<id>), pixel-art scaling, icon/text loop sync, 64-frame pruning
  services.yaml        action fields/selectors (texts are in strings.json / translations)
  strings.json         config flow string keys
  translations/en.json English strings for config/options UI
test_integration.py    standalone smoke test (mocks HA + library)
```
