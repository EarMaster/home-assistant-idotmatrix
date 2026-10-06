"""The iDotMatrix integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import COLOR_PRESETS, DOMAIN, PLATFORMS
from .coordinator import IDotMatrixDataUpdateCoordinator

SERVICE_SHOW_ICON_MESSAGE = "show_icon_message"

SHOW_ICON_MESSAGE_SCHEMA = vol.Schema({
    vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
    vol.Required("icon"): cv.string,
    vol.Required("text"): cv.string,
    vol.Optional("text_color"): vol.In(list(COLOR_PRESETS)),
    vol.Optional("icon_color"): vol.In(list(COLOR_PRESETS)),
})


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

    if not hass.services.has_service(DOMAIN, SERVICE_SHOW_ICON_MESSAGE):
        async def _handle_show_icon_message(call: ServiceCall) -> None:
            await _async_show_icon_message(hass, call)

        hass.services.async_register(
            DOMAIN, SERVICE_SHOW_ICON_MESSAGE, _handle_show_icon_message,
            schema=SHOW_ICON_MESSAGE_SCHEMA,
        )
    return True


async def _async_show_icon_message(hass: HomeAssistant, call: ServiceCall) -> None:
    """Show an icon with text below on the targeted displays.

    Values are stored just like setting the Icon & Message entities, so the
    entities reflect what is shown and Display Mode can re-send it later.
    """
    settings = {"icon": call.data["icon"].strip(), "text": call.data["text"].strip()}
    for key in ("text_color", "icon_color"):
        if key in call.data:
            settings[key] = call.data[key]

    device_registry = dr.async_get(hass)
    coordinators = {c.mac_address: c for c in hass.data.get(DOMAIN, {}).values()}
    for device_id in call.data["device_id"]:
        device = device_registry.async_get(device_id)
        mac = next((ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None) if device else None
        coordinator = coordinators.get(mac)
        if coordinator is None:
            raise ServiceValidationError(f"{device_id} is not a loaded iDotMatrix device")
        if not await coordinator.async_update_icon_message(display=True, **settings):
            raise HomeAssistantError(f"Failed to show icon & message on {coordinator.device_name}")
        await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: IDotMatrixDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SHOW_ICON_MESSAGE)
    return unloaded
