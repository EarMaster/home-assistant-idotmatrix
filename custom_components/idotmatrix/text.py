"""Text platform for iDotMatrix integration."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IDotMatrixDataUpdateCoordinator
from .entity import IDotMatrixEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the text platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        IDotMatrixText(coordinator),
        IDotMatrixImageDisplay(coordinator),
        IDotMatrixIconMessage(coordinator),
    ])


class IDotMatrixText(IDotMatrixEntity, TextEntity):
    """Representation of a text input for the iDotMatrix display."""

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator, "message")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Text: Message"
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


class IDotMatrixImageDisplay(IDotMatrixEntity, TextEntity):
    """Send any image to the display by providing a local file path or URL.

    Supported formats: PNG, JPEG, BMP, WebP (static) and GIF (animated).
    Static images are sharpened with an unsharp mask before upload to improve
    legibility on the tiny LED canvas.
    """

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the image display entity."""
        super().__init__(coordinator, "image_display")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Image: File"
        self._attr_icon = "mdi:image"
        self._attr_max = 2048
        self._attr_min = 0

    @property
    def native_value(self) -> str | None:
        """Return the last image source that was set."""
        return self.coordinator.data.get("last_image", "")

    async def async_set_value(self, value: str) -> None:
        """Display the image at the given file path or URL."""
        await self.coordinator.async_display_image(value)
        await self.coordinator.async_request_refresh()


class IDotMatrixIconMessage(IDotMatrixEntity, TextEntity):
    """Show an icon on the top portion of the display with scrolling text below.

    Value format: ``<icon_source>|<message>``

    ``<icon_source>`` is one of:
    - An MDI icon name: ``mdi:home``, ``mdi:thermometer``, ``mdi:weather-sunny``
    - A local file path: ``/config/www/icons/home.png``
    - An http(s) URL to a PNG/JPEG image

    The MDI webfont is downloaded and cached on first use.

    Examples::

        mdi:home|Welcome home!
        mdi:thermometer|23°C
        /config/www/logo.png|Server online
    """

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the icon+message entity."""
        super().__init__(coordinator, "icon_message")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Image: Icon & Message"
        self._attr_icon = "mdi:image-text"
        self._attr_max = 2048
        self._attr_min = 0

    @property
    def native_value(self) -> str | None:
        """Return the last icon+message value that was set."""
        return self.coordinator.data.get("last_icon_message", "")

    async def async_set_value(self, value: str) -> None:
        """Parse 'icon_path|message' and display the composite animation."""
        if "|" not in value:
            _LOGGER.warning(
                "Icon & Message value must be in format 'icon_source|message', got: %r", value
            )
            return
        icon_source, _, message = value.partition("|")
        icon_source = icon_source.strip()
        message = message.strip()
        if not icon_source or not message:
            return
        await self.coordinator.async_display_icon_message(icon_source, message)
        await self.coordinator.async_request_refresh()
