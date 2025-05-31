"""Text platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
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
    """Set up the text platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([IDotMatrixText(coordinator)])


class IDotMatrixText(IDotMatrixEntity, TextEntity):
    """Representation of a text input for the iDotMatrix display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator, "message")
        self._attr_name = "Message"
        self._attr_icon = "mdi:message-text"
        self._attr_max = 1000
        self._attr_min = 0

    @property
    def native_value(self) -> str | None:
        """Return the current text value."""
        return self.coordinator.data.get("last_message", "")

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        await self.coordinator.async_display_text(value)
        await self.coordinator.async_request_refresh()
