# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
