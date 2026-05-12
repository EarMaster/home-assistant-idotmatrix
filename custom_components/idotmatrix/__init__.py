"""The iDotMatrix integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import IDotMatrixDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iDotMatrix from a config entry."""
    coordinator = IDotMatrixDataUpdateCoordinator(hass, entry)
    # Set up the persistent BLE connection (non-fatal if device is out of range).
    await coordinator.async_setup_client()
    # Use async_refresh instead of async_config_entry_first_refresh so that setup
    # succeeds even when the device is temporarily out of BT range on restart.
    # Entities will be unavailable until the device connects.
    await coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: IDotMatrixDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unloaded
