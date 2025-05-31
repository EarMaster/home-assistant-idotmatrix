"""Button platform for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up the button platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        IDotMatrixResetButton(coordinator),
        IDotMatrixFreezeButton(coordinator),
        IDotMatrixChronographStartButton(coordinator),
        IDotMatrixChronographStopButton(coordinator),
        IDotMatrixChronographResetButton(coordinator),
        IDotMatrixSyncTimeButton(coordinator),
    ])


class IDotMatrixResetButton(IDotMatrixEntity, ButtonEntity):
    """Representation of device reset button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "reset")
        self._attr_name = "Reset Device"
        self._attr_icon = "mdi:restart"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_reset_device()
        await self.coordinator.async_request_refresh()


class IDotMatrixFreezeButton(IDotMatrixEntity, ButtonEntity):
    """Representation of freeze screen button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "freeze")
        self._attr_name = "Freeze Screen"
        self._attr_icon = "mdi:pause"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_freeze_screen()


class IDotMatrixChronographStartButton(IDotMatrixEntity, ButtonEntity):
    """Representation of chronograph start button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "chronograph_start")
        self._attr_name = "Start Chronograph"
        self._attr_icon = "mdi:play"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_start_chronograph()
        await self.coordinator.async_request_refresh()


class IDotMatrixChronographStopButton(IDotMatrixEntity, ButtonEntity):
    """Representation of chronograph stop button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "chronograph_stop")
        self._attr_name = "Stop Chronograph"
        self._attr_icon = "mdi:stop"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_stop_chronograph()


class IDotMatrixChronographResetButton(IDotMatrixEntity, ButtonEntity):
    """Representation of chronograph reset button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "chronograph_reset")
        self._attr_name = "Reset Chronograph"
        self._attr_icon = "mdi:restart"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_reset_chronograph()


class IDotMatrixSyncTimeButton(IDotMatrixEntity, ButtonEntity):
    """Representation of sync time button."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "sync_time")
        self._attr_name = "Sync Time"
        self._attr_icon = "mdi:clock-check"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_sync_time()
