"""Data update coordinator for iDotMatrix integration."""
from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import tempfile
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    CLOCK_STYLES,
    COLOR_PRESETS,
    CONF_MAC_ADDRESS,
    CONF_SCREEN_SIZE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCREEN_SIZE,
    DOMAIN,
    EFFECT_TYPES,
    SCREEN_SIZES,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_CLOCK_STYLE = next(iter(CLOCK_STYLES))
_DEFAULT_EFFECT_MODE = next(iter(EFFECT_TYPES))
_CLOCK_STYLE_BY_ID = {v: k for k, v in CLOCK_STYLES.items()}
_EFFECT_MODE_BY_ID = {v: k for k, v in EFFECT_TYPES.items()}

# State keys persisted to .storage/ so they survive HA restarts.
_PERSIST_KEYS = frozenset({
    "current_mode",
    "brightness", "screen_flipped",
    "clock_style", "clock_show_date", "clock_hour24", "clock_color",
    "effect_mode",
    "last_message", "last_image", "last_image_kind",
    "icon_message_icon", "icon_message_text", "icon_message_text_color", "icon_message_icon_color",
    "scoreboard_home", "scoreboard_away",
    "countdown_minutes", "countdown_seconds", "countdown_timer_entity",
})


def _parse_timer_remaining(timer_state) -> tuple[int, int] | None:
    """Return (minutes, seconds) clamped to 0–59 from an active or paused HA Timer state."""
    attrs = timer_state.attributes
    remaining: float = 0.0

    if timer_state.state == "active":
        finishes_at = attrs.get("finishes_at")
        if not finishes_at:
            return None
        finish_dt = dt_util.parse_datetime(finishes_at)
        if finish_dt is None:
            return None
        remaining = (finish_dt - dt_util.utcnow()).total_seconds()
    elif timer_state.state == "paused":
        remaining_str = attrs.get("remaining") or attrs.get("duration", "0:00:00")
        try:
            parts = remaining_str.split(":")
            if len(parts) == 3:
                remaining = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
            elif len(parts) == 2:
                remaining = int(parts[0]) * 60 + int(float(parts[1]))
            else:
                return None
        except (ValueError, AttributeError):
            return None
    else:
        return None

    total = max(0, min(3599, int(remaining)))  # clamp to 00:00–59:59
    return total // 60, total % 60


_MDI_FONT_URL = "https://cdn.jsdelivr.net/npm/@mdi/font@latest/fonts/materialdesignicons-webfont.ttf"
_MDI_CSS_URL = "https://cdn.jsdelivr.net/npm/@mdi/font@latest/css/materialdesignicons.css"
# The library's font file is not included in its pip package (fonts/ dir is at repo root,
# excluded from pyproject.toml).  We download and cache it on first use instead.
_TEXT_FONT_URL = "https://raw.githubusercontent.com/markusressel/idotmatrix-api-client/main/fonts/Rain-DRM3.otf"

# GIF upload protocol (see https://github.com/8none1/idotmatrix): the payload is sent
# in 4 KB blocks and the device notifies on fa03 after each one — 05 00 01 00 01 for
# "block received", 05 00 01 00 03 for "upload complete".
_UUID_NOTIFY_DATA = "0000fa03-0000-1000-8000-00805f9b34fb"
_UUID_WRITE_DATA = "0000fa02-0000-1000-8000-00805f9b34fb"
_GIF_ACK_PREFIX = b"\x05\x00\x01\x00"
_GIF_ACK_TIMEOUT_S = 3.0
_GIF_PACKET_DELAY_S = 0.02

# Icon & Message animation: the device handles at most 64 GIF frames.
_GIF_MAX_FRAMES = 64
_PING_PONG_PAUSE_FRAMES = 6
_PING_PONG_MS_PER_PX = 70
_PING_PONG_MAX_FRAME_MS = 150
_TEXT_GLYPH_GAP_PX = 1
_TEXT_SPACE_PX = 3
_SCROLL_PADDING_PX = 2


class IDotMatrixDataUpdateCoordinator(DataUpdateCoordinator):
    """Manage data updates for an iDotMatrix device."""

    _mdi_codepoints: dict[str, int] = {}

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.mac_address = entry.data[CONF_MAC_ADDRESS]
        self.device_name = entry.data[CONF_NAME]

        self._command_lock = asyncio.Lock()
        self._notifications: asyncio.Queue[bytes] = asyncio.Queue()
        self._connected = False
        self._countdown_timer_unsub = None
        self._state_dirty = False
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{self.mac_address}")

        self._state: dict[str, Any] = {
            "is_on": False,
            "brightness": 255,
            "screen_flipped": False,
            "current_mode": "clock",
            "clock_style": _DEFAULT_CLOCK_STYLE,
            "clock_show_date": True,
            "clock_hour24": True,
            "clock_color": "white",
            "effect_mode": _DEFAULT_EFFECT_MODE,
            "last_message": "",
            "last_image": "",
            "icon_message_icon": "mdi:information-outline",
            "icon_message_text": "",
            "last_image_kind": "file",
            "icon_message_text_color": "white",
            "icon_message_icon_color": "white",
            "scoreboard_home": 0,
            "scoreboard_away": 0,
            "countdown_minutes": 0,
            "countdown_seconds": 0,
            "countdown_timer_entity": "",
        }

        from idotmatrix.client import IDotMatrixClient
        from idotmatrix.screensize import ScreenSize

        screen_size_key = entry.data.get(CONF_SCREEN_SIZE, DEFAULT_SCREEN_SIZE)
        self.screen_size_px: int = int(screen_size_key.split("x")[0])
        self._client = IDotMatrixClient(
            screen_size=ScreenSize[SCREEN_SIZES[screen_size_key]],
            mac_address=self.mac_address,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
        )

    def _fire_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Fire a device automation event."""
        event_data = {
            "device_id": self.entry.entry_id,
            "mac_address": self.mac_address,
        }
        if data:
            event_data.update(data)
        self.hass.bus.async_fire(f"{DOMAIN}_{event_type}", event_data)

    async def async_setup_client(self) -> None:
        """Load persisted state then attempt initial BLE connection."""
        stored = await self._store.async_load()
        if stored:
            for key, value in stored.items():
                if key in _PERSIST_KEYS:
                    self._state[key] = value
            # Pre-1.8 stored icon and message combined as "icon|message".
            legacy = stored.get("last_icon_message", "")
            if "|" in legacy and "icon_message_text" not in stored:
                icon_source, _, message = legacy.partition("|")
                self._state["icon_message_icon"] = icon_source.strip()
                self._state["icon_message_text"] = message.strip()
            saved_timer = stored.get("countdown_timer_entity", "")
            if saved_timer:
                # Re-subscribe without triggering an immediate BLE command —
                # the device may not be connected yet at this point.
                self.hass.async_create_task(
                    self.async_set_countdown_timer(saved_timer, sync_now=False)
                )
        try:
            await self._ble_connect()
        except Exception as ex:
            _LOGGER.info(
                "Initial connect to %s failed, will retry on next poll: %s",
                self.mac_address, ex,
            )

    async def _ble_connect(self) -> None:
        """Connect via HA Bluetooth + bleak-retry-connector and inject client into library."""
        from homeassistant.components import bluetooth
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac_address, connectable=True
        ) or bluetooth.async_ble_device_from_address(
            self.hass, self.mac_address, connectable=False
        )
        if ble_device is None:
            raise ValueError(
                f"Device {self.mac_address} not found in HA Bluetooth scan cache"
            )

        cm = self._client._connection_manager
        client = await establish_connection(
            BleakClient,
            ble_device,
            self.mac_address,
            disconnected_callback=self._on_ble_disconnected,
            max_attempts=3,
        )
        # Suppress response reads: the library calls read_gatt_char() after every write
        # to check for a response, but on this device that characteristic is write-only.
        # The resulting "Read not permitted" GATT error causes the device to drop the
        # connection before the library's own error handler can catch it.  The library
        # ignores the response data anyway, so returning empty bytes is safe.
        async def _suppress_read(char, *args, **kwargs):
            return b""
        client.read_gatt_char = _suppress_read

        # The write characteristic only supports Write Without Response.  The library's
        # GIF and image upload paths call write_gatt_char(..., response=True) which would
        # trigger a "Write not permitted" GATT error and drop the connection.  Force every
        # write to use Write Without Response — the device receives all bytes identically
        # and the library never inspects the write acknowledgment.
        _orig_write = client.write_gatt_char
        async def _write_no_response(*args, response=False, **kwargs):
            return await _orig_write(*args, response=False, **kwargs)
        client.write_gatt_char = _write_no_response

        # The device acknowledges each 4 KB GIF block with a notification on fa03.
        # Without waiting for it, multi-block uploads overrun the device (it shows the
        # first frame or nothing at all), especially through an ESPHome BT proxy.
        try:
            await client.start_notify(_UUID_NOTIFY_DATA, self._on_ble_notification)
        except Exception as ex:
            _LOGGER.debug("Could not subscribe to notifications on %s: %s", self.mac_address, ex)

        # Inject the connected client so the library's protocol modules can send data.
        cm.client = client
        cm._connected = True
        self._connected = True
        self._state["is_on"] = True
        _LOGGER.info("Device %s connected", self.mac_address)
        self.hass.async_create_task(self.async_request_refresh())
        self.hass.async_create_task(self.async_sync_time())

    def _on_ble_notification(self, _sender, data: bytearray) -> None:
        """Forward device notifications to whoever is waiting for an upload ack."""
        _LOGGER.debug("Notification from %s: %s", self.mac_address, bytes(data).hex())
        self._notifications.put_nowait(bytes(data))

    def _on_ble_disconnected(self, client: "BleakClient") -> None:
        """Called by Bleak when the device disconnects."""
        if self._connected:
            self._connected = False
            _LOGGER.info("Device %s disconnected", self.mac_address)
            self.hass.async_create_task(self.async_request_refresh())

    @property
    def connected(self) -> bool:
        """Return True if the BLE device is currently connected."""
        return self._connected

    async def _async_update_data(self) -> dict[str, Any]:
        """Return cached state; attempt reconnect each poll cycle if disconnected."""
        if not self._connected:
            _LOGGER.debug("Device %s not connected, attempting reconnect", self.mac_address)
            try:
                await self._ble_connect()
            except Exception as ex:
                _LOGGER.debug("Reconnect attempt failed for %s: %s", self.mac_address, ex)
        if self._state_dirty:
            self._state_dirty = False
            await self._store.async_save(
                {k: self._state[k] for k in _PERSIST_KEYS if k in self._state}
            )
        return self._state.copy()

    async def _async_send_command(self, command_func, *args, **kwargs) -> bool:
        """Execute a device command under the command lock, reconnecting first if needed."""
        cm = self._client._connection_manager
        if not self._connected or not (cm.client and cm.client.is_connected):
            if self._connected:
                # BleakClient went stale without firing the disconnect callback
                _LOGGER.debug("Stale BLE client detected for %s, reconnecting", self.mac_address)
                self._connected = False
            else:
                _LOGGER.debug("Not connected to %s, attempting reconnect before command", self.mac_address)
            try:
                await self._ble_connect()
            except Exception:
                pass
        async with self._command_lock:
            try:
                await command_func(*args, **kwargs)
                self._state_dirty = True
                return True
            except Exception as ex:
                _LOGGER.warning("Command failed for %s: %s", self.mac_address, ex)
                # Only mark as disconnected if the BLE client is actually gone;
                # non-BLE errors (e.g. PIL OSError for a missing font file) must
                # not trigger a spurious disconnect/reconnect cycle.
                if self._connected and not (cm.client and cm.client.is_connected):
                    self._connected = False
                    self.hass.async_create_task(self.async_request_refresh())
                return False

    # Display control

    async def async_turn_on(self) -> bool:
        """Turn on the display."""
        success = await self._async_send_command(self._client.common.turn_on)
        if success:
            self._state["is_on"] = True
            self._fire_event("display_on")
        return success

    async def async_turn_off(self) -> bool:
        """Turn off the display."""
        success = await self._async_send_command(self._client.common.turn_off)
        if success:
            self._state["is_on"] = False
            self._fire_event("display_off")
            self._fire_event("turned_off")
        return success

    async def async_set_brightness(self, brightness: int) -> bool:
        """Set display brightness (HA 0–255 → device 5–100%)."""
        device_brightness = max(5, int((brightness / 255) * 100))
        success = await self._async_send_command(
            self._client.common.set_brightness, device_brightness
        )
        if success:
            self._state["brightness"] = brightness
            self._fire_event("brightness_changed", {"brightness": brightness})
        return success

    async def async_set_screen_flip(self, flipped: bool) -> bool:
        """Set screen rotation."""
        success = await self._async_send_command(
            self._client.common.set_screen_flipped, flipped
        )
        if success:
            self._state["screen_flipped"] = flipped
            self._fire_event("screen_flipped", {"flipped": flipped})
        return success

    # Text

    async def async_display_text(
        self,
        message: str,
        font_size: int = 24,
        color: tuple = (255, 255, 255),
        speed: int = 50,
    ) -> bool:
        """Display a scrolling text message."""
        font_path = await self._ensure_text_font()
        success = await self._async_send_command(
            self._client.text.show_text,
            message,
            font_path=font_path,
            font_size=font_size,
            text_color=color,
            speed=speed,
        )
        if success:
            self._state["last_message"] = message
            self._state["current_mode"] = "text"
            self._fire_event("text_displayed", {"message": message})
        return success

    # Clock

    async def async_set_clock_mode(self, style: int) -> bool:
        """Set clock display style, passing the stored show_date/hour24/color settings."""
        show_date = self._state.get("clock_show_date", True)
        hour24 = self._state.get("clock_hour24", True)
        color = COLOR_PRESETS.get(self._state.get("clock_color", "white"), (255, 255, 255))
        success = await self._async_send_command(
            self._client.clock.show, style,
            show_date=show_date,
            hour24=hour24,
            color=color,
        )
        if success:
            self._state["current_mode"] = "clock"
            self._state["clock_style"] = _CLOCK_STYLE_BY_ID.get(style, _DEFAULT_CLOCK_STYLE)
            self._fire_event("clock_mode_set", {"style": style})
        return success

    async def async_set_clock_show_date(self, show_date: bool) -> bool:
        """Toggle date display on the clock and re-send."""
        self._state["clock_show_date"] = show_date
        return await self.async_set_clock_mode(
            CLOCK_STYLES[self._state.get("clock_style", _DEFAULT_CLOCK_STYLE)]
        )

    async def async_set_clock_hour24(self, hour24: bool) -> bool:
        """Toggle 24-hour format on the clock and re-send."""
        self._state["clock_hour24"] = hour24
        return await self.async_set_clock_mode(
            CLOCK_STYLES[self._state.get("clock_style", _DEFAULT_CLOCK_STYLE)]
        )

    async def async_set_clock_color(self, color_name: str) -> bool:
        """Change the clock color and re-send."""
        self._state["clock_color"] = color_name
        return await self.async_set_clock_mode(
            CLOCK_STYLES[self._state.get("clock_style", _DEFAULT_CLOCK_STYLE)]
        )

    async def async_sync_time(self) -> bool:
        """Synchronize device time with Home Assistant."""
        return await self._async_send_command(
            self._client.common.set_time, dt_util.now().replace(tzinfo=None)
        )

    # Effects

    async def async_display_effect(self, effect_type: int) -> bool:
        """Display a visual effect."""
        success = await self._async_send_command(
            self._client.effect.show,
            effect_type,
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        if success:
            self._state["current_mode"] = "effect"
            self._state["effect_mode"] = _EFFECT_MODE_BY_ID.get(effect_type, _DEFAULT_EFFECT_MODE)
            self._fire_event("effect_displayed", {"effect_type": effect_type})
        return success

    # Image

    async def async_display_image(self, image_source: str, sharpen: bool = True) -> bool:
        """Display an image from a local file path or http(s) URL."""
        try:
            image_data = await self._fetch_image_data(image_source)
            is_gif = self._detect_gif(image_data)
            if not is_gif:
                image_data = await self.hass.async_add_executor_job(
                    self._process_static_image, image_data, sharpen
                )
            success = await self._upload_image_data(image_data, is_gif)
        except Exception as ex:
            _LOGGER.warning("Failed to display image %s: %s", image_source, ex)
            return False
        if success:
            self._state["current_mode"] = "image"
            self._state["last_image_kind"] = "file"
            self._state["last_image"] = image_source
            self._fire_event("image_displayed", {"source": image_source})
        return success

    async def async_display_icon_message(self) -> bool:
        """Display the stored icon on the top portion and the stored text below.

        Icon, text and colors come from the Icon & Message entities (or the
        show_icon_message action); the icon color only applies to MDI icons
        (image files keep their own colors).
        """
        icon_source = self._state.get("icon_message_icon", "").strip()
        message = self._state.get("icon_message_text", "").strip()
        if not icon_source or not message:
            _LOGGER.warning("Icon & Message needs both an icon and a text to display")
            return False
        text_color = COLOR_PRESETS.get(self._state.get("icon_message_text_color", "white"), (255, 255, 255))
        icon_color = COLOR_PRESETS.get(self._state.get("icon_message_icon_color", "white"), (255, 255, 255))
        try:
            if icon_source.startswith("mdi:"):
                icon_data = await self._get_mdi_icon_bytes(icon_source[4:], icon_color)
            else:
                icon_data = await self._fetch_image_data(icon_source)
            gif_data = await self.hass.async_add_executor_job(
                self._create_icon_message_gif,
                icon_data, message, self.screen_size_px, text_color, (0, 0, 0),
            )
            # The GIF is already canvas-sized with a tiny palette, so it skips the
            # library's normalisation (which would also cap the animation at 2 s).
            success = await self._async_send_command(self._send_gif_blocks, gif_data)
        except Exception as ex:
            _LOGGER.warning("Failed to display icon+message: %s", ex)
            return False
        if success:
            self._state["current_mode"] = "image"
            self._state["last_image_kind"] = "icon_message"
            self._fire_event("image_displayed", {"message": message})
        return success

    async def async_update_icon_message(self, display: bool = False, **settings: str) -> bool:
        """Store Icon & Message settings, then display if asked to or if it is on screen.

        settings keys: icon, text, text_color, icon_color.
        """
        for key, value in settings.items():
            self._state[f"icon_message_{key}"] = value
        on_screen = (
            self._state.get("current_mode") == "image"
            and self._state.get("last_image_kind") == "icon_message"
        )
        if display or on_screen:
            return await self.async_display_icon_message()
        return True

    async def _get_mdi_icon_bytes(self, icon_name: str, color: tuple) -> bytes:
        """Return PNG bytes for an MDI icon, downloading the font/CSS on first use."""
        font_path = self.hass.config.path(".storage/idotmatrix_mdi_font.ttf")
        css_path = self.hass.config.path(".storage/idotmatrix_mdi_icons.css")

        async def _ensure(path: str, url: str) -> None:
            exists = await self.hass.async_add_executor_job(os.path.exists, path)
            if not exists:
                _LOGGER.info("Downloading MDI asset: %s", url)
                data = await self._fetch_image_data(url)
                def _write(d: bytes) -> None:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as fh:
                        fh.write(d)
                await self.hass.async_add_executor_job(_write, data)

        await _ensure(font_path, _MDI_FONT_URL)
        await _ensure(css_path, _MDI_CSS_URL)

        # Render at exactly the icon-strip height so the glyph is pixel-exact and
        # needs no rescaling (rescaling a square render into the strip squished it).
        icon_height = max(8, int(self.screen_size_px * 0.55))
        return await self.hass.async_add_executor_job(
            self._render_mdi_icon, icon_name, font_path, css_path, icon_height, color
        )

    @classmethod
    def _render_mdi_icon(
        cls, icon_name: str, font_path: str, css_path: str, size: int, color: tuple = (255, 255, 255)
    ) -> bytes:
        """Render an MDI icon in the given color to a square RGB PNG on black."""
        import re
        from PIL import Image, ImageDraw, ImageFont

        if not cls._mdi_codepoints:
            with open(css_path, "r", encoding="utf-8") as fh:
                css = fh.read()
            # Support both ::before (CSS3) and :before (older) pseudo-element formats.
            cls._mdi_codepoints = {
                name: int(cp, 16)
                for name, cp in re.findall(
                    r'\.mdi-([\w-]+)::?before\s*\{[^}]*content:\s*"\\([0-9A-Fa-f]+)"', css
                )
            }
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "MDI codepoints loaded: %d icons from CSS", len(cls._mdi_codepoints)
            )

        codepoint = cls._mdi_codepoints.get(icon_name)
        if codepoint is None:
            raise ValueError(
                f"Unknown MDI icon: mdi:{icon_name} "
                f"(codepoints loaded: {len(cls._mdi_codepoints)})"
            )

        import logging as _logging
        _log = _logging.getLogger(__name__)

        font = ImageFont.truetype(font_path, size=max(size - 2, 8))
        img = Image.new("RGB", (size, size), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        # No anti-aliasing: grey edge pixels look muddy on an LED matrix and bloat the GIF.
        draw.fontmode = "1"
        char = chr(codepoint)
        bbox = draw.textbbox((0, 0), char, font=font)
        _log.debug(
            "MDI icon %r: codepoint U+%05X, font size %d, img %dx%d, bbox %s",
            icon_name, codepoint, max(size - 2, 8), size, size, bbox,
        )
        x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), char, font=font, fill=color)

        pixels = list(img.getdata())
        non_black = sum(1 for p in pixels if p != (0, 0, 0))
        _log.debug(
            "MDI icon %r rendered: %d/%d non-black pixels", icon_name, non_black, len(pixels)
        )

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    async def _ensure_text_font(self) -> str:
        """Return the path to the text font, downloading and caching it on first use."""
        font_path = self.hass.config.path(".storage/idotmatrix_text_font.otf")
        exists = await self.hass.async_add_executor_job(os.path.exists, font_path)
        if not exists:
            _LOGGER.info("Downloading idotmatrix text font from library repo")
            font_data = await self._fetch_image_data(_TEXT_FONT_URL)
            def _write(data: bytes) -> None:
                os.makedirs(os.path.dirname(font_path), exist_ok=True)
                with open(font_path, "wb") as fh:
                    fh.write(data)
            await self.hass.async_add_executor_job(_write, font_data)
        return font_path

    async def _fetch_image_data(self, source: str) -> bytes:
        """Return raw bytes from a local file path or http(s) URL."""
        if source.startswith(("http://", "https://")):
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(source, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    return await resp.read()
        def _read():
            with open(source, "rb") as fh:
                return fh.read()
        return await self.hass.async_add_executor_job(_read)

    async def _upload_image_data(self, image_data: bytes, is_gif: bool) -> bool:
        """Write image bytes to a temp file and upload to the device."""
        suffix = ".gif" if is_gif else ".png"

        def _write_temp(data: bytes) -> str:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(data)
            tmp.close()
            return tmp.name

        tmp_path = await self.hass.async_add_executor_job(_write_temp, image_data)
        try:
            if is_gif:
                # GIF upload uses its own command byte (1) which signals the device
                # to enter animation mode directly. Calling image.set_mode(EnableDIY)
                # first puts the device into static-image mode (command 0), which
                # causes it to ignore the subsequent GIF packets — leaving a black screen.
                return await self._async_send_command(self._upload_gif_file, tmp_path)
            ok = await self._async_send_command(self._client.image.set_mode)
            if not ok:
                return False
            return await self._async_send_command(
                self._client.image.upload_image_file, tmp_path
            )
        finally:
            await self.hass.async_add_executor_job(os.unlink, tmp_path)

    async def _upload_gif_file(self, file_path: str) -> None:
        """Normalise an arbitrary GIF with the library, then upload it block by block."""
        from idotmatrix.util.image_utils import ResizeMode

        gif_data = await self.hass.async_add_executor_job(
            self._client.gif._load_gif_and_adapt_to_canvas,
            file_path, self.screen_size_px, ResizeMode.FIT, True, (0, 0, 0), None,
        )
        await self._send_gif_blocks(gif_data)

    async def _send_gif_blocks(self, gif_data: bytes) -> None:
        """Upload canvas-sized GIF bytes block by block, waiting for the device's ack after each.

        Replaces the library's upload_gif_file(), which sends every block back to back
        without flow control. Reuses the library's packet builder.
        """
        # gif_type 12 = no time signature, same as the library's upload_gif_file()
        blocks = self._client.gif.create_gif_data_packets(gif_data, gif_type=12, time_sign=1)
        client = self._client._connection_manager.client
        _LOGGER.debug(
            "Uploading GIF to %s: %d bytes in %d block(s)", self.mac_address, len(gif_data), len(blocks)
        )

        while not self._notifications.empty():
            self._notifications.get_nowait()

        for index, block in enumerate(blocks, start=1):
            for packet in block:
                await client.write_gatt_char(_UUID_WRITE_DATA, packet, response=False)
                await asyncio.sleep(_GIF_PACKET_DELAY_S)
            ack = await self._wait_for_gif_ack()
            _LOGGER.debug(
                "GIF block %d/%d sent, ack: %s", index, len(blocks), ack.hex() if ack else "timeout"
            )

    async def _wait_for_gif_ack(self) -> bytes | None:
        """Wait for the device's block ack; return None on timeout (upload continues)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _GIF_ACK_TIMEOUT_S
        while (remaining := deadline - loop.time()) > 0:
            try:
                data = await asyncio.wait_for(self._notifications.get(), remaining)
            except asyncio.TimeoutError:
                return None
            if data.startswith(_GIF_ACK_PREFIX):
                return data
        return None

    @staticmethod
    def _detect_gif(image_data: bytes) -> bool:
        """Return True if the raw bytes start with a GIF header."""
        return image_data[:6] in (b"GIF87a", b"GIF89a")

    @staticmethod
    def _process_static_image(image_data: bytes, sharpen: bool) -> bytes:
        """Resize and optionally sharpen a static image; return PNG bytes."""
        from PIL import Image, ImageFilter, ImageOps

        img = Image.open(io.BytesIO(image_data))
        if img.mode in ("RGBA", "LA", "P"):
            if img.mode == "P":
                img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (0, 0, 0))
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        else:
            img = img.convert("RGB")
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if sharpen:
            img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    @staticmethod
    def _create_icon_message_gif(
        icon_data: bytes,
        message: str,
        screen_size: int,
        text_color: tuple,
        bg_color: tuple,
    ) -> bytes:
        """Create an animated GIF: icon in top strip, scrolling text in bottom strip."""
        from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

        icon_height = max(8, int(screen_size * 0.55))
        text_height = screen_size - icon_height

        # Prepare icon
        icon_img = Image.open(io.BytesIO(icon_data))
        if icon_img.mode in ("RGBA", "LA", "P"):
            if icon_img.mode == "P":
                icon_img = icon_img.convert("RGBA")
            bg = Image.new("RGB", icon_img.size, bg_color)
            bg.paste(icon_img, mask=icon_img.split()[-1] if icon_img.mode in ("RGBA", "LA") else None)
            icon_img = bg
        else:
            icon_img = icon_img.convert("RGB")
        try:
            icon_img = ImageOps.exif_transpose(icon_img)
        except Exception:
            pass
        # Fit into the icon strip keeping the aspect ratio, centred horizontally.
        if icon_img.size != (icon_height, icon_height):
            icon_img.thumbnail((screen_size, icon_height), Image.LANCZOS)
            icon_img = icon_img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
        icon_x = (screen_size - icon_img.width) // 2
        icon_y = (icon_height - icon_img.height) // 2

        # Render glyph by glyph, trim each to the pixels actually drawn, and join them
        # with a 1 px gap. This is tighter than the font's own 2 px spacing, and the
        # width comes from real pixels: mono (fontmode "1") glyphs are 1–2 px wider
        # than textbbox() reports, which broke the fits-or-scrolls decision.
        font = ImageFont.load_default()
        dummy = ImageDraw.Draw(Image.new("L", (1, 1)))
        bbox = dummy.textbbox((0, 0), message, font=font)
        text_y = max(0, (text_height - (bbox[3] - bbox[1])) // 2)
        glyphs = []
        for char in message:
            if char.isspace():
                glyphs.append(Image.new("L", (_TEXT_SPACE_PX, text_height), 0))
                continue
            glyph = Image.new("L", (text_height * 2, text_height), 0)
            glyph_draw = ImageDraw.Draw(glyph)
            glyph_draw.fontmode = "1"
            # Same y for every glyph keeps them on a common baseline.
            glyph_draw.text((text_height // 2, text_y - bbox[1]), char, font=font, fill=255)
            ink = glyph.getbbox()
            if ink:
                glyphs.append(glyph.crop((ink[0], 0, ink[2], text_height)))
        text_width = max(1, sum(g.width for g in glyphs) + _TEXT_GLYPH_GAP_PX * (len(glyphs) - 1))
        mask = Image.new("L", (text_width, text_height), 0)
        x = 0
        for glyph in glyphs:
            mask.paste(glyph, (x, 0))
            x += glyph.width + _TEXT_GLYPH_GAP_PX
        text_surf = Image.new("RGB", mask.size, bg_color)
        text_surf.paste(text_color, mask=mask)

        # Text that fits is shown centred and still. Longer text ping-pongs: it starts
        # left-aligned, scrolls until its right edge meets the screen edge, pauses, and
        # scrolls back, so it never leaves the screen. Frame count stays within the
        # device's 64-frame limit by scrolling more pixels per frame for long text.
        # Scrolling text keeps a small gap to the screen edges at both turning points.
        overflow = text_width + 2 * _SCROLL_PADDING_PX - screen_size
        if text_width <= screen_size:
            positions = [(screen_size - text_width) // 2]
            frame_ms = 1000
        else:
            max_steps = (_GIF_MAX_FRAMES - 2 * _PING_PONG_PAUSE_FRAMES) // 2
            step = math.ceil(overflow / max_steps)
            offsets = list(range(0, overflow, step)) + [overflow]
            positions = [_SCROLL_PADDING_PX - o for o in (
                [offsets[0]] * _PING_PONG_PAUSE_FRAMES
                + offsets[1:-1]
                + [offsets[-1]] * _PING_PONG_PAUSE_FRAMES
                + offsets[-2:0:-1]
            )]
            frame_ms = min(_PING_PONG_MAX_FRAME_MS, _PING_PONG_MS_PER_PX * step)

        frames = []
        for x in positions:
            frame = Image.new("RGB", (screen_size, screen_size), bg_color)
            frame.paste(icon_img, (icon_x, icon_y))
            frame.paste(text_surf, (x, icon_height))
            # Same palette conversion as the library's GIF normalisation.
            frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))

        import logging as _logging
        _logging.getLogger(__name__).debug(
            "icon+message GIF: screen=%d icon_height=%d text_height=%d msg_w=%d "
            "frames=%d duration=%dms",
            screen_size, icon_height, text_height, text_width, len(frames), frame_ms,
        )

        # Same encoder settings as the library: it notes optimize=False breaks uploads.
        out = io.BytesIO()
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=frame_ms,
            loop=0,
            optimize=True,
            disposal=2,
        )
        gif_bytes = out.getvalue()
        _logging.getLogger(__name__).debug(
            "icon+message GIF size: %d bytes", len(gif_bytes)
        )
        return gif_bytes

    # Scoreboard

    async def async_display_scoreboard(self, home: int, away: int) -> bool:
        """Display a scoreboard with two scores (0–999 each)."""
        success = await self._async_send_command(
            self._client.scoreboard.show, home, away
        )
        if success:
            self._state["current_mode"] = "scoreboard"
            self._state["scoreboard_home"] = home
            self._state["scoreboard_away"] = away
            self._fire_event("scoreboard_displayed", {"home": home, "away": away})
        return success

    # Countdown

    async def async_start_countdown(self, minutes: int, seconds: int) -> bool:
        """Start the countdown from the given duration (0–59 min, 0–59 sec)."""
        success = await self._async_send_command(
            self._client.countdown.start, minutes, seconds
        )
        if success:
            self._state["current_mode"] = "countdown"
            self._state["countdown_minutes"] = minutes
            self._state["countdown_seconds"] = seconds
            self._fire_event("countdown_started", {"minutes": minutes, "seconds": seconds})
        return success

    async def async_pause_countdown(self) -> bool:
        """Pause the running countdown."""
        success = await self._async_send_command(self._client.countdown.pause)
        if success:
            self._fire_event("countdown_paused")
        return success

    async def async_stop_countdown(self) -> bool:
        """Stop (disable) the countdown."""
        success = await self._async_send_command(self._client.countdown.stop)
        if success:
            self._fire_event("countdown_stopped")
        return success

    async def async_restart_countdown(self) -> bool:
        """Restart the countdown from its original duration."""
        success = await self._async_send_command(self._client.countdown.restart)
        if success:
            self._state["current_mode"] = "countdown"
            self._fire_event("countdown_restarted")
        return success

    async def async_set_countdown_timer(self, entity_id: str, *, sync_now: bool = True) -> None:
        """Link to a HA Timer entity; pass empty string to unlink.

        sync_now=False skips the immediate BLE command on load so the device
        is not contacted before the BLE connection is established.
        """
        if self._countdown_timer_unsub is not None:
            self._countdown_timer_unsub()
            self._countdown_timer_unsub = None

        self._state["countdown_timer_entity"] = entity_id
        self._state_dirty = True

        if not entity_id:
            return

        @callback
        def _on_timer_state_change(event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if new_state is None:
                return
            old_s = old_state.state if old_state else None
            new_s = new_state.state

            if new_s == "active" and old_s == "paused":
                self.hass.async_create_task(self.async_restart_countdown())
            elif new_s == "active":
                result = _parse_timer_remaining(new_state)
                if result:
                    self.hass.async_create_task(
                        self.async_start_countdown(*result)
                    )
            elif new_s == "paused":
                self.hass.async_create_task(self.async_pause_countdown())
            elif new_s == "idle":
                self.hass.async_create_task(self.async_stop_countdown())
            self.hass.async_create_task(self.async_request_refresh())

        self._countdown_timer_unsub = async_track_state_change_event(
            self.hass, entity_id, _on_timer_state_change
        )

        if not sync_now:
            return

        # Sync with the timer's current state immediately
        timer_state = self.hass.states.get(entity_id)
        if timer_state is None:
            _LOGGER.warning("Countdown timer entity %r not found", entity_id)
            return
        if timer_state.state == "active":
            result = _parse_timer_remaining(timer_state)
            if result:
                await self.async_start_countdown(*result)
        elif timer_state.state == "paused":
            result = _parse_timer_remaining(timer_state)
            if result:
                self._state["countdown_minutes"] = result[0]
                self._state["countdown_seconds"] = result[1]

    # Chronograph

    async def async_start_chronograph(self) -> bool:
        """Start the chronograph from zero."""
        success = await self._async_send_command(self._client.chronograph.start_from_zero)
        if success:
            self._state["current_mode"] = "chronograph"
            self._fire_event("chronograph_started")
        return success

    async def async_stop_chronograph(self) -> bool:
        """Pause the chronograph."""
        success = await self._async_send_command(self._client.chronograph.pause)
        if success:
            self._fire_event("chronograph_stopped")
        return success

    async def async_reset_chronograph(self) -> bool:
        """Reset the chronograph."""
        success = await self._async_send_command(self._client.chronograph.reset)
        if success:
            self._fire_event("chronograph_reset")
        return success

    async def async_freeze_screen(self) -> bool:
        """Freeze the current display."""
        return await self._async_send_command(self._client.common.freeze_screen)

    async def async_reset_device(self) -> bool:
        """Reset the device to default state."""
        success = await self._async_send_command(self._client.common.reset)
        if success:
            self._state.update({
                "is_on": True,
                "brightness": 255,
                "screen_flipped": False,
                "current_mode": "clock",
                "clock_style": _DEFAULT_CLOCK_STYLE,
            })
            self._fire_event("device_reset")
        return success

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the HA device registry."""
        return {
            "identifiers": {(DOMAIN, self.mac_address)},
            "name": self.device_name,
            "manufacturer": "iDotMatrix",
            "model": "LED Display",
            "sw_version": "1.0",
            "connections": {("mac", self.mac_address)},
        }

    async def async_shutdown(self) -> None:
        """Disconnect the BLE client cleanly on HA shutdown."""
        if self._countdown_timer_unsub is not None:
            self._countdown_timer_unsub()
            self._countdown_timer_unsub = None
        _LOGGER.info("Shutting down iDotMatrix coordinator for %s", self.mac_address)
        cm = self._client._connection_manager
        if cm.client is not None and cm.client.is_connected:
            try:
                await cm.client.disconnect()
            except Exception as ex:
                _LOGGER.debug("Error during shutdown disconnect: %s", ex)
