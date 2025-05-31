"""The iDotMatrix integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CLOCK_STYLE,
    ATTR_COLOR,
    ATTR_DURATION,
    ATTR_EFFECT_TYPE,
    ATTR_FONT_SIZE,
    ATTR_IMAGE_PATH,
    ATTR_MESSAGE,
    ATTR_SPEED,
    CLOCK_STYLES,
    COLOR_PRESETS,
    DOMAIN,
    EFFECT_TYPES,
    FONT_SIZES,
    PLATFORMS,
    SERVICE_DISPLAY_EFFECT,
    SERVICE_DISPLAY_IMAGE,
    SERVICE_DISPLAY_TEXT,
    SERVICE_SET_CLOCK_MODE,
    SERVICE_SYNC_TIME,
)
from .coordinator import IDotMatrixDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Service schemas
DISPLAY_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_FONT_SIZE, default="medium"): vol.In(FONT_SIZES.keys()),
        vol.Optional(ATTR_COLOR, default="white"): vol.Any(
            vol.In(COLOR_PRESETS.keys()),
            vol.All(vol.Length(min=3, max=3), [vol.Range(min=0, max=255)]),
        ),
        vol.Optional(ATTR_SPEED, default=50): vol.Range(min=1, max=100),
    }
)

DISPLAY_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_IMAGE_PATH): cv.string,
        vol.Optional(ATTR_DURATION, default=5): vol.Range(min=1, max=60),
    }
)

SET_CLOCK_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CLOCK_STYLE): vol.In(CLOCK_STYLES.keys()),
    }
)

DISPLAY_EFFECT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EFFECT_TYPE): vol.In(EFFECT_TYPES.keys()),
        vol.Optional(ATTR_DURATION, default=10): vol.Range(min=1, max=300),
        vol.Optional(ATTR_SPEED, default=50): vol.Range(min=1, max=100),
    }
)

SYNC_TIME_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the iDotMatrix integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iDotMatrix from a config entry."""
    coordinator = IDotMatrixDataUpdateCoordinator(hass, entry)
    
    if not await coordinator.async_connect():
        return False

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await _async_register_services(hass)
    
    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Update coordinator settings
    coordinator._scan_interval = entry.options.get("scan_interval", coordinator._scan_interval)
    coordinator._connection_timeout = entry.options.get("connection_timeout", coordinator._connection_timeout)
    coordinator._max_retries = entry.options.get("retry_attempts", coordinator._max_retries)
    
    # Update the update interval
    from datetime import timedelta
    coordinator.update_interval = timedelta(seconds=coordinator._scan_interval)
    
    # Request a refresh to apply new settings
    await coordinator.async_request_refresh()


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    
    async def handle_display_text(call: ServiceCall) -> None:
        """Handle display text service call."""
        message = call.data[ATTR_MESSAGE]
        font_size = FONT_SIZES[call.data[ATTR_FONT_SIZE]]
        color = call.data[ATTR_COLOR]
        speed = call.data[ATTR_SPEED]
        
        # Convert color name to RGB tuple if needed
        if isinstance(color, str):
            color = COLOR_PRESETS.get(color, COLOR_PRESETS["white"])
        
        # Find all coordinators and send command
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, IDotMatrixDataUpdateCoordinator):
                await coordinator.async_display_text(message, font_size, color, speed)

    async def handle_display_image(call: ServiceCall) -> None:
        """Handle display image service call."""
        image_path = call.data[ATTR_IMAGE_PATH]
        duration = call.data[ATTR_DURATION]
        
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, IDotMatrixDataUpdateCoordinator):
                await coordinator.async_display_image(image_path, duration)

    async def handle_set_clock_mode(call: ServiceCall) -> None:
        """Handle set clock mode service call."""
        clock_style = CLOCK_STYLES[call.data[ATTR_CLOCK_STYLE]]
        
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, IDotMatrixDataUpdateCoordinator):
                await coordinator.async_set_clock_mode(clock_style)

    async def handle_display_effect(call: ServiceCall) -> None:
        """Handle display effect service call."""
        effect_type = EFFECT_TYPES[call.data[ATTR_EFFECT_TYPE]]
        duration = call.data[ATTR_DURATION]
        speed = call.data[ATTR_SPEED]
        
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, IDotMatrixDataUpdateCoordinator):
                await coordinator.async_display_effect(effect_type, duration, speed)

    async def handle_sync_time(call: ServiceCall) -> None:
        """Handle sync time service call."""
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, IDotMatrixDataUpdateCoordinator):
                await coordinator.async_sync_time()

    # Register services
    hass.services.async_register(
        DOMAIN, SERVICE_DISPLAY_TEXT, handle_display_text, schema=DISPLAY_TEXT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISPLAY_IMAGE, handle_display_image, schema=DISPLAY_IMAGE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLOCK_MODE, handle_set_clock_mode, schema=SET_CLOCK_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISPLAY_EFFECT, handle_display_effect, schema=DISPLAY_EFFECT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_TIME, handle_sync_time, schema=SYNC_TIME_SCHEMA
    )
