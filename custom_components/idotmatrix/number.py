"""Number platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up the number platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        IDotMatrixScoreboardHome(coordinator),
        IDotMatrixScoreboardAway(coordinator),
        IDotMatrixCountdownMinutes(coordinator),
        IDotMatrixCountdownSeconds(coordinator),
    ])


class _IDotMatrixScoreboardNumber(IDotMatrixEntity, NumberEntity):
    _attr_native_min_value = 0.0
    _attr_native_max_value = 999.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG


class IDotMatrixScoreboardHome(_IDotMatrixScoreboardNumber):
    """Home team score for the scoreboard display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "scoreboard_home")
        self._attr_name = "Scoreboard: Home"
        self._attr_icon = "mdi:scoreboard"

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data.get("scoreboard_home", 0))

    async def async_set_native_value(self, value: float) -> None:
        away = self.coordinator.data.get("scoreboard_away", 0)
        await self.coordinator.async_display_scoreboard(int(value), away)
        await self.coordinator.async_request_refresh()


class IDotMatrixScoreboardAway(_IDotMatrixScoreboardNumber):
    """Away team score for the scoreboard display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "scoreboard_away")
        self._attr_name = "Scoreboard: Away"
        self._attr_icon = "mdi:scoreboard-outline"

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data.get("scoreboard_away", 0))

    async def async_set_native_value(self, value: float) -> None:
        home = self.coordinator.data.get("scoreboard_home", 0)
        await self.coordinator.async_display_scoreboard(home, int(value))
        await self.coordinator.async_request_refresh()


class _IDotMatrixCountdownNumber(IDotMatrixEntity, NumberEntity):
    _attr_native_min_value = 0.0
    _attr_native_max_value = 59.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG


class IDotMatrixCountdownMinutes(_IDotMatrixCountdownNumber):
    """Minutes component of the countdown duration (0–59)."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "countdown_minutes")
        self._attr_name = "Countdown: Minutes"
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data.get("countdown_minutes", 0))

    async def async_set_native_value(self, value: float) -> None:
        secs = self.coordinator.data.get("countdown_seconds", 0)
        await self.coordinator.async_start_countdown(int(value), secs)
        await self.coordinator.async_request_refresh()


class IDotMatrixCountdownSeconds(_IDotMatrixCountdownNumber):
    """Seconds component of the countdown duration (0–59)."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "countdown_seconds")
        self._attr_name = "Countdown: Seconds"
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data.get("countdown_seconds", 0))

    async def async_set_native_value(self, value: float) -> None:
        mins = self.coordinator.data.get("countdown_minutes", 0)
        await self.coordinator.async_start_countdown(mins, int(value))
        await self.coordinator.async_request_refresh()
