"""Data update coordinator for iDotMatrix integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CLOCK_STYLES,
    CONF_MAC_ADDRESS,
    CONF_SCREEN_SIZE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCREEN_SIZE,
    DOMAIN,
    EFFECT_TYPES,
    SCREEN_SIZES,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_CLOCK_STYLE = next(iter(CLOCK_STYLES))
_DEFAULT_EFFECT_MODE = next(iter(EFFECT_TYPES))
_CLOCK_STYLE_BY_ID = {v: k for k, v in CLOCK_STYLES.items()}
_EFFECT_MODE_BY_ID = {v: k for k, v in EFFECT_TYPES.items()}


class IDotMatrixDataUpdateCoordinator(DataUpdateCoordinator):
    """Manage data updates for an iDotMatrix device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.mac_address = entry.data[CONF_MAC_ADDRESS]
        self.device_name = entry.data[CONF_NAME]

        self._command_lock = asyncio.Lock()
        self._connected = False

        self._state: dict[str, Any] = {
            "is_on": False,
            "brightness": 255,
            "screen_flipped": False,
            "current_mode": "clock",
            "clock_style": _DEFAULT_CLOCK_STYLE,
            "effect_mode": _DEFAULT_EFFECT_MODE,
            "last_message": "",
        }

        from idotmatrix.client import IDotMatrixClient
        from idotmatrix.screensize import ScreenSize

        screen_size_key = entry.data.get(CONF_SCREEN_SIZE, DEFAULT_SCREEN_SIZE)
        self._client = IDotMatrixClient(
            screen_size=ScreenSize[SCREEN_SIZES[screen_size_key]],
            mac_address=self.mac_address,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
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

    async def async_setup_client(self) -> None:
        """Register connection listener, enable auto-reconnect, attempt initial connect."""
        from idotmatrix.connection_manager import ConnectionListener

        self._client.add_connection_listener(ConnectionListener(
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        ))
        self._client.set_auto_reconnect(True)
        try:
            await self._client.connect()
        except Exception as ex:
            _LOGGER.debug(
                "Initial connect to %s failed, will retry automatically: %s",
                self.mac_address, ex,
            )

    async def _on_connected(self) -> None:
        """Called by the library when the device connects."""
        self._connected = True
        self.hass.async_create_task(self.async_request_refresh())

    async def _on_disconnected(self) -> None:
        """Called by the library when the device disconnects."""
        self._connected = False
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> dict[str, Any]:
        """Return current state; raise UpdateFailed when not connected."""
        if not self._connected:
            raise UpdateFailed(f"Device {self.mac_address} not connected")
        return self._state.copy()

    async def _async_send_command(self, command_func, *args, **kwargs) -> bool:
        """Execute a device command under the command lock."""
        async with self._command_lock:
            try:
                await command_func(*args, **kwargs)
                return True
            except Exception as ex:
                _LOGGER.error("Error sending command to %s: %s", self.mac_address, ex)
                return False

    # Display control

    async def async_turn_on(self) -> bool:
        """Turn on the display."""
        success = await self._async_send_command(self._client.common.turn_on)
        if success:
            self._state["is_on"] = True
            self._fire_event("display_on")
        return success

    async def async_turn_off(self) -> bool:
        """Turn off the display."""
        success = await self._async_send_command(self._client.common.turn_off)
        if success:
            self._state["is_on"] = False
            self._fire_event("display_off")
            self._fire_event("turned_off")
        return success

    async def async_set_brightness(self, brightness: int) -> bool:
        """Set display brightness (HA 0–255 → device 5–100%)."""
        device_brightness = max(5, int((brightness / 255) * 100))
        success = await self._async_send_command(
            self._client.common.set_brightness, device_brightness
        )
        if success:
            self._state["brightness"] = brightness
            self._fire_event("brightness_changed", {"brightness": brightness})
        return success

    async def async_set_screen_flip(self, flipped: bool) -> bool:
        """Set screen rotation."""
        success = await self._async_send_command(
            self._client.common.set_screen_flipped, flipped
        )
        if success:
            self._state["screen_flipped"] = flipped
            self._fire_event("screen_flipped", {"flipped": flipped})
        return success

    # Text

    async def async_display_text(
        self,
        message: str,
        font_size: int = 12,
        color: tuple = (255, 255, 255),
        speed: int = 50,
    ) -> bool:
        """Display a scrolling text message."""
        success = await self._async_send_command(
            self._client.text.show_text,
            message,
            font_size=font_size,
            text_color=color,
            speed=speed,
        )
        if success:
            self._state["last_message"] = message
            self._state["current_mode"] = "text"
            self._fire_event("text_displayed", {"message": message})
        return success

    # Clock

    async def async_set_clock_mode(self, style: int) -> bool:
        """Set clock display style."""
        success = await self._async_send_command(self._client.clock.show, style)
        if success:
            self._state["current_mode"] = "clock"
            self._state["clock_style"] = _CLOCK_STYLE_BY_ID.get(style, _DEFAULT_CLOCK_STYLE)
            self._fire_event("clock_mode_set", {"style": style})
        return success

    async def async_sync_time(self) -> bool:
        """Synchronize device time with Home Assistant."""
        return await self._async_send_command(
            self._client.common.set_time, datetime.now()
        )

    # Effects

    async def async_display_effect(self, effect_type: int) -> bool:
        """Display a visual effect."""
        success = await self._async_send_command(
            self._client.effect.show,
            effect_type,
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        if success:
            self._state["current_mode"] = "effect"
            self._state["effect_mode"] = _EFFECT_MODE_BY_ID.get(effect_type, _DEFAULT_EFFECT_MODE)
            self._fire_event("effect_displayed", {"effect_type": effect_type})
        return success

    # Image

    async def async_display_image(self, image_path: str, duration: int = 5) -> bool:
        """Display an image or GIF."""
        self._state["current_mode"] = "image"
        self._fire_event("image_displayed", {"image_path": image_path})
        return True

    # Chronograph

    async def async_start_chronograph(self) -> bool:
        """Start the chronograph from zero."""
        success = await self._async_send_command(self._client.chronograph.start_from_zero)
        if success:
            self._state["current_mode"] = "chronograph"
            self._fire_event("chronograph_started")
        return success

    async def async_stop_chronograph(self) -> bool:
        """Pause the chronograph."""
        success = await self._async_send_command(self._client.chronograph.pause)
        if success:
            self._fire_event("chronograph_stopped")
        return success

    async def async_reset_chronograph(self) -> bool:
        """Reset the chronograph."""
        success = await self._async_send_command(self._client.chronograph.reset)
        if success:
            self._fire_event("chronograph_reset")
        return success

    async def async_freeze_screen(self) -> bool:
        """Freeze the current display."""
        return await self._async_send_command(self._client.common.freeze_screen)

    async def async_reset_device(self) -> bool:
        """Reset the device to default state."""
        success = await self._async_send_command(self._client.common.reset)
        if success:
            self._state.update({
                "is_on": True,
                "brightness": 255,
                "screen_flipped": False,
                "current_mode": "clock",
                "clock_style": _DEFAULT_CLOCK_STYLE,
            })
            self._fire_event("device_reset")
        return success

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the HA device registry."""
        return {
            "identifiers": {(DOMAIN, self.mac_address)},
            "name": self.device_name,
            "manufacturer": "iDotMatrix",
            "model": "LED Display",
            "sw_version": "1.0",
            "connections": {("mac", self.mac_address)},
        }

    async def async_shutdown(self) -> None:
        """Stop auto-reconnect and disconnect cleanly."""
        _LOGGER.info("Shutting down iDotMatrix coordinator for %s", self.mac_address)
        self._client.set_auto_reconnect(False)
        await self._client.disconnect()
