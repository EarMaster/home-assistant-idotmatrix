# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
