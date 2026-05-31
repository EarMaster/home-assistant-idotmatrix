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
        IDotMatrixDisplayModeSelect(coordinator),
        IDotMatrixClockStyleSelect(coordinator),
        IDotMatrixEffectSelect(coordinator),
    ])


class IDotMatrixDisplayModeSelect(IDotMatrixEntity, SelectEntity):
    """Select that shows the active display mode and lets you switch between modes.

    Selecting a mode re-activates the last content sent for that mode (e.g.
    selecting 'clock' re-sends the current clock style; selecting 'text'
    re-sends the last scrolling message).  The option always reflects what is
    currently on the display — it updates automatically whenever any other
    entity (Message, Clock Style, Effect Mode, …) changes the content.
    """

    _MODES = ["clock", "text", "effect", "image", "chronograph"]

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "current_mode")
        self._attr_name = "Display Mode"
        self._attr_icon = "mdi:monitor-dashboard"
        self._attr_options = self._MODES

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("current_mode", "clock")

    async def async_select_option(self, option: str) -> None:
        if option == "clock":
            style_name = self.coordinator.data.get("clock_style", next(iter(CLOCK_STYLES)))
            await self.coordinator.async_set_clock_mode(CLOCK_STYLES[style_name])
        elif option == "text":
            msg = self.coordinator.data.get("last_message", "")
            if msg:
                await self.coordinator.async_display_text(msg)
        elif option == "effect":
            effect_name = self.coordinator.data.get("effect_mode", next(iter(EFFECT_TYPES)))
            await self.coordinator.async_display_effect(EFFECT_TYPES[effect_name])
        elif option == "image":
            src = self.coordinator.data.get("last_image", "")
            icon_msg = self.coordinator.data.get("last_icon_message", "")
            if src:
                await self.coordinator.async_display_image(src)
            elif icon_msg and "|" in icon_msg:
                icon_source, _, message = icon_msg.partition("|")
                await self.coordinator.async_display_icon_message(
                    icon_source.strip(), message.strip()
                )
        elif option == "chronograph":
            await self.coordinator.async_start_chronograph()
        await self.coordinator.async_request_refresh()


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
        return self.coordinator.data.get("clock_style", self._attr_options[0])

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
        return self.coordinator.data.get("effect_mode", self._attr_options[0])

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        effect_id = EFFECT_TYPES[option]
        await self.coordinator.async_display_effect(effect_id)
        await self.coordinator.async_request_refresh()
