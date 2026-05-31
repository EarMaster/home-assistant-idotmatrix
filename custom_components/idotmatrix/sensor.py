"""Sensor platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([IDotMatrixCurrentModeSensor(coordinator)])


class IDotMatrixCurrentModeSensor(IDotMatrixEntity, SensorEntity):
    """Sensor reporting which content mode is currently active on the display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "current_mode")
        self._attr_name = "Current Mode"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str | None:
        """Return the active display mode."""
        return self.coordinator.data.get("current_mode")
