"""Switch platform for iDotMatrix integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IDotMatrixDataUpdateCoordinator
from .entity import IDotMatrixEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        IDotMatrixScreenFlipSwitch(coordinator),
        IDotMatrixClock24HourSwitch(coordinator),
        IDotMatrixClockShowDateSwitch(coordinator),
    ])


class IDotMatrixScreenFlipSwitch(IDotMatrixEntity, SwitchEntity):
    """Representation of screen flip/rotation switch."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "screen_flip")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Screen Flip"
        self._attr_icon = "mdi:screen-rotation"

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self.coordinator.data.get("screen_flipped", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.async_set_screen_flip(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.async_set_screen_flip(False)
        await self.coordinator.async_request_refresh()


class IDotMatrixClock24HourSwitch(IDotMatrixEntity, SwitchEntity):
    """Toggle 24-hour vs 12-hour clock format."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "clock_hour24")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Clock: 24-Hour Format"
        self._attr_icon = "mdi:clock-digital"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("clock_hour24", True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_clock_hour24(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_clock_hour24(False)
        await self.coordinator.async_request_refresh()


class IDotMatrixClockShowDateSwitch(IDotMatrixEntity, SwitchEntity):
    """Toggle date display alongside the clock."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "clock_show_date")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Clock: Show Date"
        self._attr_icon = "mdi:calendar-clock"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("clock_show_date", True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_clock_show_date(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_clock_show_date(False)
        await self.coordinator.async_request_refresh()
