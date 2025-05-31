"""Data update coordinator for iDotMatrix integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONNECTION_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_RETRIES,
    RECONNECT_INTERVAL,
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
        
        # Get configuration options
        self._scan_interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        self._connection_timeout = entry.options.get("connection_timeout", CONNECTION_TIMEOUT)
        self._max_retries = entry.options.get("retry_attempts", MAX_RETRIES)
        
        self._connection_manager = None
        self._device = None
        self._connected = False
        self._command_lock = asyncio.Lock()
        self._retry_count = 0
        
        # Device state tracking
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
            update_interval=timedelta(seconds=self._scan_interval),
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
        try:
            from idotmatrix import ConnectionManager
            
            self._connection_manager = ConnectionManager()
            self._device = await self._connection_manager.connect(
                self.mac_address, timeout=self._connection_timeout
            )
            
            if self._device:
                self._connected = True
                self._retry_count = 0
                _LOGGER.info("Connected to iDotMatrix device %s", self.mac_address)
                return True
            else:
                _LOGGER.error("Failed to connect to device %s", self.mac_address)
                return False
                
        except Exception as ex:
            _LOGGER.exception("Error connecting to device %s: %s", self.mac_address, ex)
            return False

    async def async_disconnect(self) -> None:
        """Disconnect from the device."""
        if self._device and self._connected:
            try:
                await self._device.disconnect()
            except Exception as ex:
                _LOGGER.error("Error disconnecting from device: %s", ex)
            finally:
                self._connected = False
                self._device = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        if not self._connected:
            if self._retry_count < self._max_retries:
                _LOGGER.warning("Device disconnected, attempting to reconnect...")
                if await self.async_connect():
                    self._retry_count = 0
                else:
                    self._retry_count += 1
            else:
                raise UpdateFailed(f"Failed to connect to device after {self._max_retries} attempts")
        
        # Since the library doesn't provide state reading, we return our tracked state
        return self._state.copy()

    async def _async_send_command(self, command_func, *args, **kwargs) -> bool:
        """Send a command to the device with error handling."""
        async with self._command_lock:
            if not self._connected or not self._device:
                _LOGGER.error("Device not connected")
                return False
            
            try:
                await command_func(*args, **kwargs)
                return True
            except Exception as ex:
                _LOGGER.error("Error sending command: %s", ex)
                self._connected = False
                return False

    # Display control methods    async def async_turn_on(self) -> bool:
        """Turn on the display."""
        from idotmatrix.common import Common
        
        success = await self._async_send_command(
            Common(self._device).turn_on_device
        )
        if success:
            self._state["is_on"] = True
            self._fire_event("display_on")
        return success

    async def async_turn_off(self) -> bool:
        """Turn off the display."""
        from idotmatrix.common import Common
        
        success = await self._async_send_command(
            Common(self._device).turn_off_device
        )
        if success:
            self._state["is_on"] = False
            self._fire_event("display_off")
            self._fire_event("turned_off")
        return success

    async def async_set_brightness(self, brightness: int) -> bool:
        """Set the display brightness."""
        from idotmatrix.common import Common
        
        # Convert HA brightness (0-255) to device brightness (0-100)
        device_brightness = int((brightness / 255) * 100)
        
        success = await self._async_send_command(
            Common(self._device).set_brightness,
            device_brightness
        )
        if success:
            self._state["brightness"] = brightness
            self._fire_event("brightness_changed", {"brightness": brightness})
        return success

    async def async_set_screen_flip(self, flipped: bool) -> bool:
        """Set screen rotation/flip."""
        from idotmatrix.common import Common
        
        success = await self._async_send_command(
            Common(self._device).set_screen_rotation,
            180 if flipped else 0
        )
        if success:
            self._state["screen_flipped"] = flipped
            self._fire_event("screen_flipped", {"flipped": flipped})
        return success

    # Text display methods
    async def async_display_text(self, message: str, font_size: int = 12, color: tuple = (255, 255, 255), speed: int = 50) -> bool:
        """Display text message."""
        from idotmatrix.text import Text
        
        success = await self._async_send_command(
            Text(self._device).send_text,
            message,
            font_size=font_size,
            color=color,
            speed=speed
        )
        if success:
            self._state["last_message"] = message
            self._state["current_mode"] = "text"
            self._fire_event("text_displayed", {"message": message})
        return success

    # Clock methods
    async def async_set_clock_mode(self, style: int) -> bool:
        """Set clock display mode."""
        from idotmatrix.clock import Clock
        
        success = await self._async_send_command(
            Clock(self._device).set_clock_style,
            style
        )
        if success:
            self._state["current_mode"] = "clock"
            # Map style number back to name for state tracking
            style_names = {0: "classic", 1: "digital", 2: "analog", 3: "minimal", 4: "colorful"}
            self._state["clock_style"] = style_names.get(style, "classic")
            self._fire_event("clock_mode_set", {"style": style})
        return success

    async def async_sync_time(self) -> bool:
        """Synchronize device time with Home Assistant."""
        from idotmatrix.clock import Clock
        
        current_time = datetime.now()
        success = await self._async_send_command(
            Clock(self._device).sync_time,
            current_time
        )
        return success

    # Effect methods
    async def async_display_effect(self, effect_type: int, duration: int = 10, speed: int = 50) -> bool:
        """Display visual effect."""
        from idotmatrix.effects import Effects
        
        success = await self._async_send_command(
            Effects(self._device).show_effect,
            effect_type,
            duration=duration,
            speed=speed
        )
        if success:
            self._state["current_mode"] = "effect"
            # Map effect number back to name for state tracking
            effect_names = {0: "rainbow", 1: "breathing", 2: "wave", 3: "fire", 4: "snow", 5: "matrix", 6: "stars", 7: "plasma"}
            self._state["effect_mode"] = effect_names.get(effect_type, "rainbow")
            self._fire_event("effect_displayed", {"effect_type": effect_type})
        return success

    # Image display methods
    async def async_display_image(self, image_path: str, duration: int = 5) -> bool:
        """Display an image or GIF."""
        # This would need to be implemented based on the actual library capabilities
        # For now, just track the state
        self._state["current_mode"] = "image"
        self._fire_event("image_displayed", {"image_path": image_path})
        return True

    # Chronograph methods
    async def async_start_chronograph(self) -> bool:
        """Start the chronograph."""
        from idotmatrix.chronograph import Chronograph
        
        success = await self._async_send_command(
            Chronograph(self._device).start
        )
        if success:
            self._state["current_mode"] = "chronograph"
            self._fire_event("chronograph_started")
        return success

    async def async_stop_chronograph(self) -> bool:
        """Stop the chronograph."""
        from idotmatrix.chronograph import Chronograph
        
        success = await self._async_send_command(
            Chronograph(self._device).stop
        )
        if success:
            self._fire_event("chronograph_stopped")
        return success

    async def async_reset_chronograph(self) -> bool:
        """Reset the chronograph."""
        from idotmatrix.chronograph import Chronograph
        
        success = await self._async_send_command(
            Chronograph(self._device).reset
        )
        if success:
            self._fire_event("chronograph_reset")
        return success

    async def async_freeze_screen(self) -> bool:
        """Freeze the current display."""
        from idotmatrix.common import Common
        
        success = await self._async_send_command(
            Common(self._device).freeze_screen
        )
        return success

    async def async_reset_device(self) -> bool:
        """Reset the device."""
        from idotmatrix.common import Common
        
        success = await self._async_send_command(
            Common(self._device).reset_device
        )
        if success:
            # Reset state to defaults
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
