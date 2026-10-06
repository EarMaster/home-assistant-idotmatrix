"""Text platform for iDotMatrix integration."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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

    # The combined "icon|message" entity was replaced by separate Icon and Text
    # entities; drop its registry entry so it doesn't linger as unavailable.
    registry = er.async_get(hass)
    if old_entity_id := registry.async_get_entity_id(
        "text", DOMAIN, f"{coordinator.mac_address}_icon_message"
    ):
        registry.async_remove(old_entity_id)

    async_add_entities([
        IDotMatrixText(coordinator),
        IDotMatrixImageDisplay(coordinator),
        IDotMatrixIconMessageIcon(coordinator),
        IDotMatrixIconMessageText(coordinator),
        IDotMatrixCountdownTimer(coordinator),
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


class IDotMatrixIconMessageIcon(IDotMatrixEntity, TextEntity):
    """Icon shown in the top portion of the display by Icon & Message.

    One of:
    - An MDI icon name: ``mdi:home``, ``mdi:thermometer``, ``mdi:weather-sunny``
      (the MDI webfont is downloaded and cached on first use)
    - A local file path: ``/config/www/icons/home.png``
    - An http(s) URL to a PNG/JPEG image

    Changing it re-sends the message if Icon & Message is currently on screen.
    """

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the icon entity."""
        super().__init__(coordinator, "icon_message_icon")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Icon & Message: Icon"
        self._attr_icon = "mdi:emoticon-outline"
        self._attr_max = 255
        self._attr_min = 0

    @property
    def native_value(self) -> str | None:
        """Return the stored icon."""
        return self.coordinator.data.get("icon_message_icon", "")

    async def async_set_value(self, value: str) -> None:
        """Store the icon and refresh the display if the message is showing."""
        await self.coordinator.async_update_icon_message(icon=value.strip())
        await self.coordinator.async_request_refresh()


class IDotMatrixIconMessageText(IDotMatrixEntity, TextEntity):
    """Text shown below the icon; setting it displays Icon & Message.

    Text that fits is shown still and centred; longer text scrolls ping-pong style.
    """

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator, "icon_message_text")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Icon & Message: Text"
        self._attr_icon = "mdi:image-text"
        self._attr_max = 255
        self._attr_min = 0

    @property
    def native_value(self) -> str | None:
        """Return the stored text."""
        return self.coordinator.data.get("icon_message_text", "")

    async def async_set_value(self, value: str) -> None:
        """Store the text and display icon + text."""
        await self.coordinator.async_update_icon_message(display=True, text=value.strip())
        await self.coordinator.async_request_refresh()


class IDotMatrixCountdownTimer(IDotMatrixEntity, TextEntity):
    """Optional link to a Home Assistant Timer entity for automatic countdown sync.

    Set to a ``timer.*`` entity ID (e.g. ``timer.kitchen``) to have the iDotMatrix
    countdown mirror that timer automatically: starting, pausing, restarting, and
    stopping in sync with the HA timer.  Clear the field to disable the link.
    """

    def __init__(self, coordinator: IDotMatrixDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "countdown_timer")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_name = "Countdown: Timer Entity"
        self._attr_icon = "mdi:timer-sync"
        self._attr_max = 255
        self._attr_min = 0

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("countdown_timer_entity", "")

    async def async_set_value(self, value: str) -> None:
        entity_id = value.strip()
        if entity_id and not entity_id.startswith("timer."):
            _LOGGER.warning(
                "Countdown timer entity must be a timer.* entity ID, got: %r", entity_id
            )
            return
        await self.coordinator.async_set_countdown_timer(entity_id)
        await self.coordinator.async_request_refresh()
