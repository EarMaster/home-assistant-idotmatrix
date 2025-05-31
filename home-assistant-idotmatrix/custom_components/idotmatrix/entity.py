"""Base entity for iDotMatrix integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IDotMatrixDataUpdateCoordinator


class IDotMatrixEntity(CoordinatorEntity[IDotMatrixDataUpdateCoordinator]):
    """Base class for iDotMatrix entities."""

    def __init__(
        self,
        coordinator: IDotMatrixDataUpdateCoordinator,
        entity_suffix: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_suffix = entity_suffix
        self._attr_unique_id = f"{coordinator.mac_address}_{entity_suffix}"
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac_address)},
            name=self.coordinator.device_name,
            manufacturer="iDotMatrix",
            model="LED Display",
            sw_version="1.0",
            connections={("mac", self.coordinator.mac_address)},
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator._connected
