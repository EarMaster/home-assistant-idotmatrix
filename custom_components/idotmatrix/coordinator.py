"""Data update coordinator for iDotMatrix integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MAC_ADDRESS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class IDotMatrixDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.hass = hass
        self.mac_address = entry.data[CONF_MAC_ADDRESS]
        self.device_name = entry.data[CONF_NAME]

        self._connection_manager = None
        self._command_lock = asyncio.Lock()

        self._state = {
            "is_on": False,
            "brightness": 255,
            "screen_flipped": False,
            "current_mode": "clock",
            "clock_style": "classic",
            "effect_mode": "rainbow",
            "last_message": "",
        }

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )

    def _fire_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Fire a device automation event."""
        event_data = {
            "device_id": self.entry.entry_id,
            "mac_address": self.mac_address,
        }
        if data:
            event_data.update(data)
        self.hass.bus.async_fire(f"{DOMAIN}_{event_type}", event_data)

    async def async_connect(self) -> bool:
        """Connect to the device."""
        from bleak import BleakClient
        from homeassistant.components.bluetooth import async_ble_device_from_address
        from idotmatrix import ConnectionManager

        # habluetooth requires a BLEDevice object (not a plain MAC string) to
        # route the connection to the correct adapter.
        ble_device = async_ble_device_from_address(
            self.hass, self.mac_address, connectable=True
        )
        if not ble_device:
            _LOGGER.debug(
                "Device %s not in HA Bluetooth registry — not in range yet",
                self.mac_address,
            )
            return False

        self._connection_manager = ConnectionManager()
        self._connection_manager.address = self.mac_address
        self._connection_manager.client = BleakClient(ble_device)
        await self._connection_manager.client.connect()
        return self._connection_manager.client.is_connected

    async def async_disconnect(self) -> None:
        """Disconnect from the device."""
        if (
            self._connection_manager is not None
            and self._connection_manager.client is not None
            and self._connection_manager.client.is_connected
        ):
            try:
                await self._connection_manager.client.disconnect()
            except Exception as ex:
                _LOGGER.debug("Error disconnecting: %s", ex)
            finally:
                self._connection_manager.client = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Return locally tracked state — no read-back from device possible."""
        return self._state.copy()

    async def _async_send_command(self, command_func, *args, **kwargs) -> bool:
        """Connect, send a command, then disconnect.

        BLE is not designed for persistent connections — connect-on-demand
        avoids dropped-connection errors between commands.
        """
        async with self._command_lock:
            try:
                if not await self.async_connect():
                    _LOGGER.warning("Cannot reach %s — device may be off or out of range", self.mac_address)
                    return False
                await command_func(*args, **kwargs)
                return True
            except Exception as ex:
                _LOGGER.error("Error sending command to %s: %s", self.mac_address, ex)
                return False
            finally:
                await self.async_disconnect()

    # Display control methods

    async def async_turn_on(self) -> bool:
        """Turn on the display."""
        from idotmatrix import Common

        success = await self._async_send_command(Common().screenOn)
        if success:
            self._state["is_on"] = True
            self._fire_event("display_on")
        return success

    async def async_turn_off(self) -> bool:
        """Turn off the display."""
        from idotmatrix import Common

        success = await self._async_send_command(Common().screenOff)
        if success:
            self._state["is_on"] = False
            self._fire_event("display_off")
            self._fire_event("turned_off")
        return success

    async def async_set_brightness(self, brightness: int) -> bool:
        """Set the display brightness."""
        from idotmatrix import Common

        # Convert HA brightness (0-255) to device brightness (0-100)
        device_brightness = int((brightness / 255) * 100)

        success = await self._async_send_command(
            Common().setBrightness, device_brightness
        )
        if success:
            self._state["brightness"] = brightness
            self._fire_event("brightness_changed", {"brightness": brightness})
        return success

    async def async_set_screen_flip(self, flipped: bool) -> bool:
        """Set screen rotation/flip."""
        from idotmatrix import Common

        success = await self._async_send_command(Common().flipScreen, flipped)
        if success:
            self._state["screen_flipped"] = flipped
            self._fire_event("screen_flipped", {"flipped": flipped})
        return success

    # Text display methods

    async def async_display_text(
        self, message: str, font_size: int = 12, color: tuple = (255, 255, 255), speed: int = 50
    ) -> bool:
        """Display text message."""
        from idotmatrix import Text

        success = await self._async_send_command(
            Text().setMode, message, font_size=font_size, text_color=color, speed=speed
        )
        if success:
            self._state["last_message"] = message
            self._state["current_mode"] = "text"
            self._fire_event("text_displayed", {"message": message})
        return success

    # Clock methods

    async def async_set_clock_mode(self, style: int) -> bool:
        """Set clock display mode."""
        from idotmatrix import Clock

        success = await self._async_send_command(Clock().setMode, style)
        if success:
            self._state["current_mode"] = "clock"
            style_names = {0: "classic", 1: "digital", 2: "analog", 3: "minimal", 4: "colorful"}
            self._state["clock_style"] = style_names.get(style, "classic")
            self._fire_event("clock_mode_set", {"style": style})
        return success

    async def async_sync_time(self) -> bool:
        """Synchronize device time with Home Assistant."""
        from idotmatrix import Common

        now = datetime.now()
        return await self._async_send_command(
            Common().setTime, now.year, now.month, now.day, now.hour, now.minute, now.second
        )

    # Effect methods

    async def async_display_effect(self, effect_type: int) -> bool:
        """Display visual effect."""
        from idotmatrix import Effect

        success = await self._async_send_command(
            Effect().setMode, effect_type, [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        )
        if success:
            self._state["current_mode"] = "effect"
            effect_names = {
                0: "rainbow", 1: "random_pixels", 2: "white", 3: "rainbow_vertical",
                4: "diagonal_right", 5: "diagonal_left", 6: "random",
            }
            self._state["effect_mode"] = effect_names.get(effect_type, "rainbow")
            self._fire_event("effect_displayed", {"effect_type": effect_type})
        return success

    # Image display methods

    async def async_display_image(self, image_path: str, duration: int = 5) -> bool:
        """Display an image or GIF."""
        self._state["current_mode"] = "image"
        self._fire_event("image_displayed", {"image_path": image_path})
        return True

    # Chronograph methods

    async def async_start_chronograph(self) -> bool:
        """Start the chronograph."""
        from idotmatrix import Chronograph

        success = await self._async_send_command(Chronograph().setMode, 1)
        if success:
            self._state["current_mode"] = "chronograph"
            self._fire_event("chronograph_started")
        return success

    async def async_stop_chronograph(self) -> bool:
        """Stop the chronograph."""
        from idotmatrix import Chronograph

        success = await self._async_send_command(Chronograph().setMode, 2)
        if success:
            self._fire_event("chronograph_stopped")
        return success

    async def async_reset_chronograph(self) -> bool:
        """Reset the chronograph."""
        from idotmatrix import Chronograph

        success = await self._async_send_command(Chronograph().setMode, 0)
        if success:
            self._fire_event("chronograph_reset")
        return success

    async def async_freeze_screen(self) -> bool:
        """Freeze the current display."""
        from idotmatrix import Common

        return await self._async_send_command(Common().freezeScreen)

    async def async_reset_device(self) -> bool:
        """Reset the device."""
        from idotmatrix import Common

        success = await self._async_send_command(Common().reset)
        if success:
            self._state.update({
                "is_on": True,
                "brightness": 255,
                "screen_flipped": False,
                "current_mode": "clock",
                "clock_style": "classic",
            })
            self._fire_event("device_reset")
        return success

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.mac_address)},
            "name": self.device_name,
            "manufacturer": "iDotMatrix",
            "model": "LED Display",
            "sw_version": "1.0",
            "connections": {("mac", self.mac_address)},
        }

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and disconnect from the device."""
        _LOGGER.info("Shutting down iDotMatrix coordinator for %s", self.mac_address)
        await self.async_disconnect()
