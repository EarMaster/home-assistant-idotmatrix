"""Image platform for iDotMatrix integration: a preview of what the display shows."""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import preview
from .const import DOMAIN
from .coordinator import IDotMatrixDataUpdateCoordinator
from .entity import IDotMatrixEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the image platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([IDotMatrixPreviewImage(hass, coordinator)])


class IDotMatrixPreviewImage(IDotMatrixEntity, ImageEntity):
    """Upscaled (animated) GIF of what the display is showing.

    Exact for images and Icon & Message, approximate for scrolling text, and a
    labelled fallback (icon + live value) for modes the device draws itself.
    """

    _attr_content_type = "image/gif"

    def __init__(self, hass: HomeAssistant, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the preview entity."""
        super().__init__(coordinator, "display_preview")
        ImageEntity.__init__(self, hass)
        self._attr_name = "Display Preview"
        self._attr_icon = "mdi:monitor-eye"
        self._attr_image_last_updated = coordinator.preview_version
        self._cached: tuple | None = None  # (preview_version, upscaled bytes)

    @property
    def available(self) -> bool:
        """Keep showing the last known content while the display is out of range."""
        return self.coordinator.preview_native is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        # Only a content change bumps image_last_updated, which makes the frontend
        # refetch; the recorder writes a row per change, so never per frame.
        if self.coordinator.preview_version != self._attr_image_last_updated:
            self._attr_image_last_updated = self.coordinator.preview_version
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return the preview, upscaled with sharp pixels (cached per version)."""
        native = self.coordinator.preview_native
        if native is None:
            return None
        version = self.coordinator.preview_version
        if self._cached is None or self._cached[0] != version:
            upscaled = await self.hass.async_add_executor_job(
                preview.upscale_gif, native, preview.upscale_factor(self.coordinator.screen_size_px)
            )
            self._cached = (version, upscaled)
        return self._cached[1]
