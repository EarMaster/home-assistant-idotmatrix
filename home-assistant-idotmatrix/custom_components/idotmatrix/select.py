"""Select platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLOCK_STYLES, DOMAIN, EFFECT_TYPES
from .coordinator import IDotMatrixDataUpdateCoordinator
from .entity import IDotMatrixEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        IDotMatrixClockStyleSelect(coordinator),
        IDotMatrixEffectSelect(coordinator),
    ])


class IDotMatrixClockStyleSelect(IDotMatrixEntity, SelectEntity):
    """Representation of clock style selector."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "clock_style")
        self._attr_name = "Clock Style"
        self._attr_icon = "mdi:clock"
        self._attr_options = list(CLOCK_STYLES.keys())

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self.coordinator.data.get("clock_style", "classic")

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        style_id = CLOCK_STYLES[option]
        await self.coordinator.async_set_clock_mode(style_id)
        await self.coordinator.async_request_refresh()


class IDotMatrixEffectSelect(IDotMatrixEntity, SelectEntity):
    """Representation of effect selector."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "effect_mode")
        self._attr_name = "Effect Mode"
        self._attr_icon = "mdi:palette"
        self._attr_options = list(EFFECT_TYPES.keys())

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self.coordinator.data.get("effect_mode", "rainbow")

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        effect_id = EFFECT_TYPES[option]
        await self.coordinator.async_display_effect(effect_id)
        await self.coordinator.async_request_refresh()
