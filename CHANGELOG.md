# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
