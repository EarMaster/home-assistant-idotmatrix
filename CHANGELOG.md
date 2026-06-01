# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.1] - 2026-06-01

### Fixed
- Display entity no longer shows as off after HA restart or reconnect; state is now set to on whenever a BLE connection is established (the device has no readable on/off characteristic, so connected = on)

## [1.5.0] - 2026-06-01

### Added
- Device page now shows a separate **Configuration** section (alongside Controls) for settings-style entities, using `EntityCategory.CONFIG`

### Changed
- Entity display names follow a consistent `Mode: Detail` pattern so related items sort together: `Clock: Style`, `Effect: Mode`, `Text: Message`, `Image: File`, `Image: Icon & Message`, `Chronograph: Start/Stop/Reset`
- Entity IDs are unchanged — existing automations and scripts continue to work without modification

## [1.4.0] - 2026-05-31

### Added
- **Display Mode select**: replaces the v1.3.0 read-only sensor with an interactive select entity. Shows the active mode (`clock`, `text`, `effect`, `image`, `chronograph`) and lets you switch back to any mode — selecting one re-activates the last content sent for that type. The value updates automatically whenever any other entity changes the display, so no separate "Auto" mode is needed.

### Changed
- Removed the `Current Mode` sensor entity introduced in v1.3.0 (superseded by Display Mode select above). If you were using `sensor.idotmatrix_current_mode` in automations, update the reference to `select.idotmatrix_current_mode`.

## [1.3.1] - 2026-05-31

### Fixed
- All commands broken after the v1.3.0 write-without-response patch: the wrapper function declared its first parameter as `char` but the library passes it as the keyword argument `char_specifier`, causing every write to raise a `TypeError`. Switched the wrapper to `*args` so it is agnostic to parameter names.

## [1.3.0] - 2026-05-31

### Added
- **Current Mode sensor**: new read-only entity showing which content is currently active on the display (`clock`, `text`, `effect`, `image`, or `chronograph`)

### Fixed
- **Image and Icon & Message now work**: all GATT writes are forced to Write Without Response. The device's write characteristic does not support Write with Acknowledgment; the library's GIF and image upload paths were using `response=True`, causing a silent GATT error and leaving the display unchanged.
- **Text inter-character spacing**: default font size raised from 12 to 24. At size 12 the `Rain-DRM3.otf` glyphs rendered as ~8×8 px inside the library's fixed 16×32 px per-character cell, leaving large empty gaps between characters. At size 24 the glyphs fill the full 16 px cell width.

## [1.2.3] - 2026-05-28

### Fixed
- Clock now shows the correct time: replaced `datetime.now()` (system/UTC time) with `dt_util.now()` which respects the timezone configured in Home Assistant.
- Time is automatically synchronized with HA whenever the device connects, so the clock is always correct without needing to press the Sync Time button manually.

## [1.2.2] - 2026-05-28

### Fixed
- Text display now works: the library's font file (`Rain-DRM3.otf`) is not shipped with the pip package, so every `show_text` call raised `OSError: cannot open resource`. The coordinator now downloads and caches the font on first use.
- `OSError` and other non-BLE exceptions in `_async_send_command` no longer trigger a spurious BLE disconnect/reconnect cycle. Only errors where `client.is_connected` is `False` actually mark the device as disconnected.
- Icon & Message entity logs a `WARNING` instead of silently returning when the value is missing the required `|` separator (e.g. `mdi:home|Hello`).

## [1.2.1] - 2026-05-28

### Fixed
- Suppress `read_gatt_char` response reads after every BLE write — the device's write characteristic does not support reads, causing a `Read not permitted` GATT error that dropped the connection before commands could take effect.
- Detect stale BleakClient in `_async_send_command`: if the client's `is_connected` property is False even though `_connected` is True (disconnect callback missed), reconnect before attempting the command instead of failing with `cannot open resource`.

## [1.2.0] - 2026-05-27

### Added
- **Display Image** entity (`text`): send any PNG, JPEG, BMP, WebP, or animated GIF to the display by setting a local file path or http(s) URL. Static images are sharpened with an unsharp mask before upload to improve legibility on the small LED canvas. GIFs pass through to the device's native GIF module.
- **Icon & Message** entity (`text`): display an icon in the top ~55 % of the screen with a scrolling text message in the bottom strip. The composite is uploaded as an animated GIF within the device limits (≤ 64 frames, ≤ 2 000 ms). Icon source accepts:
  - MDI icon names (`mdi:home`, `mdi:thermometer`, `mdi:weather-sunny`, …) — the MDI webfont and CSS codepoint map are downloaded from jsDelivr CDN and cached in `.storage/` on first use
  - Local file paths (`/config/www/icons/home.png`)
  - http(s) URLs
- `async_display_image` in the coordinator is now fully implemented (was previously a no-op stub).

## [1.1.7] - 2026-05-25

### Fixed
- **Device not found in HA Bluetooth scan cache** even though it was visible in HA's Bluetooth device list. `async_ble_device_from_address` with `connectable=True` returns `None` for devices that were only seen by a passive Bluetooth observer (e.g. an ESPHome Bluetooth proxy in passive mode). Both the coordinator and the config flow discovery now fall back to `connectable=False`, which returns the passive-scan entry and lets `bleak_retry_connector` find the best connection path.

## [1.1.6] - 2026-05-25

### Fixed
- **Devices failed to connect on HA 2025.x** with "No backend with an available connection slot that can reach address X was found". HA's Bluetooth subsystem requires a `BLEDevice` object from its scan cache rather than a raw MAC string. The coordinator now uses `bluetooth.async_ble_device_from_address()` and `bleak_retry_connector.establish_connection()`, injecting the resulting authenticated client into the library's `ConnectionManager`, bypassing the library's own broken connection path entirely.
- Shutdown disconnect now operates on the injected `BleakClient` directly rather than calling the library's `disconnect()`.

## [1.1.5] - 2026-05-25

### Fixed
- **Devices never connected** due to a Bleak ≥0.22 incompatibility in the upstream library. `connect_by_address()` tried to mutate `BleakClient._backend.address`, but `_backend` is `None` until after `connect()` completes in newer Bleak versions. Fixed by calling `ConnectionManager.connect()` directly, bypassing the broken `set_address()` path entirely.

## [1.1.4] - 2026-05-25

### Fixed
- Device no longer stays unavailable indefinitely after a BLE drop. The coordinator now actively calls `connect()` on every poll cycle (every 30 s by default) while disconnected, supplementing the library's passive auto-reconnect timer.
- Restored INFO-level log entries for connect/disconnect events and initial connect failures, so connection state changes are visible in HA logs without enabling debug mode.

## [1.1.3] - 2026-05-25

### Fixed
- BLE disconnection no longer generates spurious `ERROR` log entries. The coordinator now returns cached state instead of raising `UpdateFailed` when the device is temporarily out of range; entity availability is tracked via the `connected` property, so entities still go unavailable correctly while auto-reconnect retries in the background.
- Commands issued while disconnected now attempt an explicit reconnect before failing.

## [1.1.2] - 2026-05-25

### Fixed
- BLE command failures now immediately mark the device as disconnected and trigger auto-reconnect, rather than silently staying "available" until the next 30-second poll. Entities switch to unavailable right away when a command cannot be delivered to the device.

## [1.1.1] - 2026-05-13

### Fixed
- Device discovery was broken because `idotmatrix>=0.1.0` does not exist on PyPI (the markusressel library has not been published there yet). The requirement now installs directly from the GitHub repository using a pip URL requirement, which HA supports for custom integrations.

## [1.1.0] - 2026-05-13

### Breaking Changes
- Clock style names have changed to match the new library's `ClockStyle` enum. The previous values (`classic`, `digital`, `analog`, `minimal`, `colorful`) are no longer valid. New values are: `RGB Swipe Outline`, `Christmas Tree`, `Checkers`, `Color`, `Hourglass`, `Alarm Clock`, `Outlines`, `RGB Corners`. Update any automations or scripts that reference clock styles.
- Effect type names have changed. Previous values (`rainbow`, `random_pixels`, etc.) are replaced with: `Horizontal Rainbow`, `Random Colored Pixels`, `White on Changing BG`, `Vertical Rainbow`, `Diagonal Right Rainbow`, `Diagonal Left Rainbow`, `Random Colored`.
- The options flow no longer exposes `connection_timeout` or `retry_attempts` — these are now managed automatically by the library.

### Added
- **Screen size selection** in the configuration flow. When adding a device you are now asked to specify the display resolution (16×16, 32×32, or 64×64 pixels). This is required by the new library. The default is 32×32, which matches most IDM- devices.
- **Persistent Bluetooth connection with automatic reconnect.** The integration now maintains a live BLE connection and lets the library retry every 5 seconds when the device goes out of range, instead of creating a fresh connection for every command.
- Availability updates are now immediate: entities switch to unavailable as soon as the device disconnects and become available again the moment the connection is restored, rather than waiting for the next 30-second poll.

### Changed
- Upgraded from the archived `derkalle4/python3-idotmatrix-library` to `markusressel/idotmatrix-api-client` (≥0.1.0), which is actively maintained and has a cleaner module-based API.
- Chronograph "Stop" button now pauses the chronograph (the new library has `pause()` but no discrete `stop()`).

## [1.0.7] - 2026-05-12

### Fixed
- After a Home Assistant restart, previously configured devices no longer show "Setup error, retrying" while the Bluetooth scanner has not yet seen the device advertisement. The integration now starts up successfully and marks entities as unavailable until the device is detected — no user action required.

## [1.0.6] - 2026-05-12

### Fixed
- All entities were permanently marked unavailable because the `available` property checked a `_connected` attribute that does not exist on the coordinator. Availability is now correctly derived from the Bluetooth advertisement cache check performed by the periodic update.
- Config flow labels and options were displayed as raw translation keys instead of human-readable strings because `translations/en.json` was missing.

## [1.0.5] - 2026-05-12

### Added
- Periodic availability check: the coordinator now polls HA's Bluetooth advertisement cache every 30 seconds (configurable). If the device has not been seen recently, all entities are marked unavailable in Home Assistant and recover automatically when the device comes back in range.

### Fixed
- Bluetooth connections are no longer kept alive between commands. Each command now connects, sends, and disconnects in one atomic operation. This prevents the "dropped connection" errors that occurred when the device closed an idle BLE link.
- The initial config flow dialog no longer shows a pointless "scan for devices" checkbox — it now opens the device list directly.

## [1.0.4] - 2026-05-12

### Fixed
- Bluetooth connection failed with "No backend with an available connection slot" because the `idotmatrix` library was passing a raw MAC address string to `BleakClient`. Home Assistant's `habluetooth` layer requires a `BLEDevice` object to route the connection to the correct adapter. The coordinator now retrieves the `BLEDevice` from HA's Bluetooth registry via `async_ble_device_from_address` before connecting.

## [1.0.3] - 2026-05-12

### Fixed
- Integration failed to load entirely with "No setup or config entry setup function defined" because `__init__.py` was empty. Added `async_setup_entry` and `async_unload_entry`, which are required by Home Assistant to initialise the coordinator, register platforms, and clean up on removal.
- Config flow discovery step threw a 500 Internal Server Error when no devices were found, because the description string referenced a `{devices_found}` placeholder that was not passed in the error path. Removed the placeholder from the description.

## [1.0.2] - 2026-05-12

### Fixed
- All device command methods in the coordinator now call the correct `idotmatrix` library API. Every method name was mismatched (e.g. `turn_on_device` instead of `screenOn`, `set_brightness` instead of `setBrightness`, `Clock().sync_time` instead of `Common().setTime`, `Chronograph().start/.stop/.reset` instead of `Chronograph().setMode(1/2/0)`, etc.) — none of the device commands were functional before this fix.
- `Effect.setMode` is now called with the correct signature (`style`, `rgb_values`) instead of the non-existent `show_effect(effect_type, duration, speed)`.
- Effect type constants and the `display_effect` service definition updated to match the seven styles (0–6) the library actually supports, removing the invalid `breathing`, `wave`, `fire`, `snow`, `matrix`, `stars`, and `plasma` entries.
- Time sync now correctly calls `Common().setTime(year, month, day, hour, minute, second)` instead of the non-existent `Clock().sync_time(datetime)`.

## [1.0.1] - 2026-05-12

### Added
- Native Home Assistant Bluetooth auto-discovery: iDotMatrix devices are now automatically surfaced in the HA "Discovered" flow when the HA Bluetooth integration picks them up, without requiring a manual scan.
- Bluetooth confirm step in the config flow UI so users can approve a discovered device before adding it.

### Fixed
- `async_turn_on` method was accidentally merged into a comment, making the display power-on command unreachable. It is now correctly defined.
- Bluetooth connection now uses `connectByAddress` to match the actual `idotmatrix` library API instead of the non-existent `connect` method.
- All library imports updated to use top-level `idotmatrix` package imports instead of internal submodule paths (`idotmatrix.common`, `idotmatrix.clock`, etc.).
- Device connection state now accurately reflects the underlying BleakClient's `is_connected` flag via a dedicated `_is_connected()` helper, preventing stale connection assumptions.
- Added `bluetooth` as an explicit Home Assistant dependency in `manifest.json` so the Bluetooth integration is guaranteed to load before this integration.

### Changed
- Device discovery during manual setup now uses HA's `async_discovered_service_info()` instead of spawning a competing BleakScanner, preventing Bluetooth connection conflicts.
