"""Actions (services) for the iDotMatrix integration.

Entities are the primary interface; these actions exist for what entities can't
offer: pickers (icon, color, duration), several settings in one call, and
temporary content that returns to the previous screen (restore_after).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import COLOR_PRESETS, DOMAIN
from .coordinator import IDotMatrixDataUpdateCoordinator

SERVICE_SHOW_ICON_MESSAGE = "show_icon_message"
SERVICE_SHOW_TEXT = "show_text"
SERVICE_START_COUNTDOWN = "start_countdown"
SERVICE_SET_SCOREBOARD = "set_scoreboard"
SERVICES = (SERVICE_SHOW_ICON_MESSAGE, SERVICE_SHOW_TEXT, SERVICE_START_COUNTDOWN, SERVICE_SET_SCOREBOARD)

ATTR_RESTORE_AFTER = "restore_after"
COUNTDOWN_MAX = timedelta(minutes=59, seconds=59)  # device limit


def _rgb_color(value):
    """Accept a preset color name or an [r, g, b] list (what the color picker sends)."""
    if isinstance(value, str) and value in COLOR_PRESETS:
        return list(COLOR_PRESETS[value])
    try:
        return list(vol.Schema(vol.ExactSequence((cv.byte, cv.byte, cv.byte)))(list(value)))
    except (vol.Invalid, TypeError) as ex:
        raise vol.Invalid(
            f"expected [r, g, b] with values 0–255 or one of {', '.join(COLOR_PRESETS)}, got {value!r}"
        ) from ex


def _countdown_duration(value) -> timedelta:
    duration = cv.time_period(value)
    if not timedelta(seconds=1) <= duration <= COUNTDOWN_MAX:
        raise vol.Invalid("countdown duration must be between 0:00:01 and 0:59:59")
    return duration


def _schema(fields: dict) -> vol.All:
    """Action schema with the standard target fields (device, entity or area)."""
    return vol.All(
        vol.Schema({
            vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
            vol.Optional(ATTR_AREA_ID): vol.All(cv.ensure_list, [cv.string]),
            **fields,
        }),
        cv.has_at_least_one_key(ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_AREA_ID),
    )


_RESTORE_AFTER = {vol.Optional(ATTR_RESTORE_AFTER): cv.positive_time_period}

SCHEMAS = {
    SERVICE_SHOW_ICON_MESSAGE: _schema({
        vol.Required("icon"): cv.string,
        vol.Required("text"): cv.string,
        vol.Optional("text_color"): _rgb_color,
        vol.Optional("icon_color"): _rgb_color,
        **_RESTORE_AFTER,
    }),
    SERVICE_SHOW_TEXT: _schema({
        vol.Required("text"): cv.string,
        vol.Optional("color"): _rgb_color,
        vol.Optional("font_size"): vol.All(vol.Coerce(int), vol.Range(min=8, max=32)),
        vol.Optional("speed"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        **_RESTORE_AFTER,
    }),
    SERVICE_START_COUNTDOWN: _schema({
        vol.Required("duration"): _countdown_duration,
        **_RESTORE_AFTER,
    }),
    SERVICE_SET_SCOREBOARD: _schema({
        vol.Optional("home"): vol.All(vol.Coerce(int), vol.Range(min=0, max=999)),
        vol.Optional("away"): vol.All(vol.Coerce(int), vol.Range(min=0, max=999)),
    }),
}


def _target_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[IDotMatrixDataUpdateCoordinator]:
    """Resolve the action target (devices, entities, areas) to loaded displays."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    device_ids = set(call.data.get(ATTR_DEVICE_ID, []))
    for entity_id in call.data.get(ATTR_ENTITY_ID, []):
        if (entry := entity_registry.async_get(entity_id)) and entry.device_id:
            device_ids.add(entry.device_id)
    for area_id in call.data.get(ATTR_AREA_ID, []):
        device_ids.update(d.id for d in dr.async_entries_for_area(device_registry, area_id))
        device_ids.update(
            e.device_id for e in er.async_entries_for_area(entity_registry, area_id) if e.device_id
        )

    by_mac = {c.mac_address: c for c in hass.data.get(DOMAIN, {}).values()}
    coordinators = []
    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            continue
        mac = next((ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None)
        if (coordinator := by_mac.get(mac)) is not None:
            coordinators.append(coordinator)
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_target_display"
        )
    return coordinators


async def _async_run(
    coordinator: IDotMatrixDataUpdateCoordinator,
    call: ServiceCall,
    show: Callable[[], Awaitable[bool]],
    restore_extra: timedelta = timedelta(0),
) -> None:
    """Show content on one display, optionally restoring the previous screen later."""
    restore_after: timedelta | None = call.data.get(ATTR_RESTORE_AFTER)
    snapshot = coordinator.snapshot_for_restore() if restore_after is not None else None
    if not await show():
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="action_failed",
            translation_placeholders={"device": coordinator.device_name},
        )
    if snapshot is not None:
        coordinator.schedule_restore(snapshot, restore_extra + restore_after)
    await coordinator.async_request_refresh()


def _color_settings(data: dict[str, Any], **keys: str) -> dict[str, Any]:
    return {target: data[source] for source, target in keys.items() if source in data}


async def _show_icon_message(coordinator: IDotMatrixDataUpdateCoordinator, call: ServiceCall) -> None:
    settings = {
        "icon": call.data["icon"].strip(),
        "text": call.data["text"].strip(),
        **_color_settings(call.data, text_color="text_color", icon_color="icon_color"),
    }
    await _async_run(
        coordinator, call, lambda: coordinator.async_update_icon_message(display=True, **settings)
    )


async def _show_text(coordinator: IDotMatrixDataUpdateCoordinator, call: ServiceCall) -> None:
    await _async_run(coordinator, call, lambda: coordinator.async_display_text(
        call.data["text"],
        font_size=call.data.get("font_size"),
        color=call.data.get("color"),
        speed=call.data.get("speed"),
    ))


async def _start_countdown(coordinator: IDotMatrixDataUpdateCoordinator, call: ServiceCall) -> None:
    total = int(call.data["duration"].total_seconds())
    # restore_after counts from the end of the countdown
    await _async_run(
        coordinator, call,
        lambda: coordinator.async_start_countdown(total // 60, total % 60),
        restore_extra=call.data["duration"],
    )


async def _set_scoreboard(coordinator: IDotMatrixDataUpdateCoordinator, call: ServiceCall) -> None:
    home = call.data.get("home", coordinator.data.get("scoreboard_home", 0))
    away = call.data.get("away", coordinator.data.get("scoreboard_away", 0))
    await _async_run(coordinator, call, lambda: coordinator.async_display_scoreboard(home, away))


_HANDLERS = {
    SERVICE_SHOW_ICON_MESSAGE: _show_icon_message,
    SERVICE_SHOW_TEXT: _show_text,
    SERVICE_START_COUNTDOWN: _start_countdown,
    SERVICE_SET_SCOREBOARD: _set_scoreboard,
}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions (once, shared by all displays)."""
    for service, handler in _HANDLERS.items():
        if hass.services.has_service(DOMAIN, service):
            continue

        async def _handle(call: ServiceCall, handler=handler) -> None:
            for coordinator in _target_coordinators(hass, call):
                await handler(coordinator, call)

        hass.services.async_register(DOMAIN, service, _handle, schema=SCHEMAS[service])


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the actions once the last display is unloaded."""
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
