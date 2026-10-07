"""Select platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLOCK_STYLES, COLOR_PRESETS, DOMAIN, EFFECT_TYPES
from .coordinator import IDotMatrixDataUpdateCoordinator
from .entity import IDotMatrixEntity

_CUSTOM_COLOR = "custom"


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
        IDotMatrixClockColorSelect(coordinator),
        IDotMatrixEffectSelect(coordinator),
        IDotMatrixIconMessageColorSelect(coordinator, "text"),
        IDotMatrixIconMessageColorSelect(coordinator, "icon"),
    ])


class IDotMatrixDisplayModeSelect(IDotMatrixEntity, SelectEntity):
    """Select that shows the active display mode and lets you switch between modes.

    Selecting a mode re-activates the last content sent for that mode (e.g.
    selecting 'clock' re-sends the current clock style; selecting 'text'
    re-sends the last scrolling message).  The option always reflects what is
    currently on the display — it updates automatically whenever any other
    entity (Message, Clock Style, Effect Mode, …) changes the content.
    """

    _MODES = ["clock", "text", "effect", "image", "chronograph", "scoreboard", "countdown"]

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "current_mode")
        self._attr_name = "Display Mode"
        self._attr_icon = "mdi:monitor-dashboard"
        self._attr_options = self._MODES

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("current_mode", "clock")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_activate_mode(option)
        await self.coordinator.async_request_refresh()


class IDotMatrixClockStyleSelect(IDotMatrixEntity, SelectEntity):
    """Representation of clock style selector."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "clock_style")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Clock: Style"
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


class IDotMatrixClockColorSelect(IDotMatrixEntity, SelectEntity):
    """Color selector for the clock display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "clock_color")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Clock: Color"
        self._attr_icon = "mdi:palette"
        self._attr_options = list(COLOR_PRESETS.keys())

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("clock_color", "white")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_clock_color(option)
        await self.coordinator.async_request_refresh()


class IDotMatrixIconMessageColorSelect(IDotMatrixEntity, SelectEntity):
    """Text or icon color for Image: Icon & Message (icon color applies to MDI icons only)."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator, target: str) -> None:
        super().__init__(coordinator, f"icon_message_{target}_color")
        self._target = target
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = f"Icon & Message: {target.capitalize()} Color"
        self._attr_icon = "mdi:palette"
        # "custom" is shown when the show_icon_message action set a non-preset color.
        self._attr_options = [*COLOR_PRESETS, _CUSTOM_COLOR]

    @property
    def current_option(self) -> str | None:
        rgb = tuple(self.coordinator.data.get(f"icon_message_{self._target}_color", (255, 255, 255)))
        return next((name for name, preset in COLOR_PRESETS.items() if preset == rgb), _CUSTOM_COLOR)

    async def async_select_option(self, option: str) -> None:
        if option == _CUSTOM_COLOR:
            return  # keep the current custom color; set new ones via the action
        await self.coordinator.async_update_icon_message(
            **{f"{self._target}_color": list(COLOR_PRESETS[option])}
        )
        await self.coordinator.async_request_refresh()


class IDotMatrixEffectSelect(IDotMatrixEntity, SelectEntity):
    """Representation of effect selector."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "effect_mode")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Effect: Mode"
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
