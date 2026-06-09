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
    "last_message", "last_image", "last_icon_message",
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


class IDotMatrixDataUpdateCoordinator(DataUpdateCoordinator):
    """Manage data updates for an iDotMatrix device."""

    _mdi_codepoints: dict[str, int] = {}

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.mac_address = entry.data[CONF_MAC_ADDRESS]
        self.device_name = entry.data[CONF_NAME]

        self._command_lock = asyncio.Lock()
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
            "last_icon_message": "",
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

        # Inject the connected client so the library's protocol modules can send data.
        cm.client = client
        cm._connected = True
        self._connected = True
        self._state["is_on"] = True
        _LOGGER.info("Device %s connected", self.mac_address)
        self.hass.async_create_task(self.async_request_refresh())
        self.hass.async_create_task(self.async_sync_time())

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
            self._state["last_image"] = image_source
            self._fire_event("image_displayed", {"source": image_source})
        return success

    async def async_display_icon_message(
        self,
        icon_source: str,
        message: str,
        text_color: tuple = (255, 255, 255),
        bg_color: tuple = (0, 0, 0),
    ) -> bool:
        """Display an icon on the top portion and scrolling text on the bottom."""
        try:
            if icon_source.startswith("mdi:"):
                icon_data = await self._get_mdi_icon_bytes(icon_source[4:])
            else:
                icon_data = await self._fetch_image_data(icon_source)
            gif_data = await self.hass.async_add_executor_job(
                self._create_icon_message_gif,
                icon_data, message, self.screen_size_px, text_color, bg_color,
            )
            success = await self._upload_image_data(gif_data, is_gif=True)
        except Exception as ex:
            _LOGGER.warning("Failed to display icon+message: %s", ex)
            return False
        if success:
            self._state["current_mode"] = "image"
            self._state["last_icon_message"] = f"{icon_source}|{message}"
            self._fire_event("image_displayed", {"message": message})
        return success

    async def _get_mdi_icon_bytes(self, icon_name: str) -> bytes:
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

        # Render at the full icon-strip height (55% of screen) so the glyph
        # fills the available space.  Previously used 55% as both image size
        # AND font size, producing a tiny 17×17 output for a 32×32 screen.
        icon_height = max(8, int(self.screen_size_px * 0.55))
        render_size = max(icon_height, self.screen_size_px)
        return await self.hass.async_add_executor_job(
            self._render_mdi_icon, icon_name, font_path, css_path, render_size
        )

    @classmethod
    def _render_mdi_icon(cls, icon_name: str, font_path: str, css_path: str, size: int) -> bytes:
        """Render an MDI icon to a square white-on-black RGB PNG."""
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
        char = chr(codepoint)
        bbox = draw.textbbox((0, 0), char, font=font)
        _log.debug(
            "MDI icon %r: codepoint U+%05X, font size %d, img %dx%d, bbox %s",
            icon_name, codepoint, max(size - 2, 8), size, size, bbox,
        )
        x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), char, font=font, fill=(255, 255, 255))

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
                return await self._async_send_command(
                    self._client.gif.upload_gif_file, tmp_path
                )
            ok = await self._async_send_command(self._client.image.set_mode)
            if not ok:
                return False
            return await self._async_send_command(
                self._client.image.upload_image_file, tmp_path
            )
        finally:
            await self.hass.async_add_executor_job(os.unlink, tmp_path)

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
        icon_img = icon_img.resize((screen_size, icon_height), Image.LANCZOS)
        icon_img = icon_img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))

        # Measure text using default bitmap font
        font = ImageFont.load_default()
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = dummy.textbbox((0, 0), message, font=font)
        text_width = bbox[2] - bbox[0]
        char_height = bbox[3] - bbox[1]
        text_y = max(0, (text_height - char_height) // 2)

        # Build wide text surface: leading blank + text + trailing blank
        surface_w = screen_size + text_width + screen_size
        text_surf = Image.new("RGB", (surface_w, text_height), bg_color)
        ImageDraw.Draw(text_surf).text((screen_size, text_y), message, font=font, fill=text_color)

        # Calculate frame count to stay within device GIF limits (64 frames, 2000 ms total)
        total_scroll = screen_size + text_width
        max_frames = 60
        px_per_frame = max(1, math.ceil(total_scroll / max_frames))
        num_frames = math.ceil(total_scroll / px_per_frame)
        frame_ms = max(16, math.floor(2000 / num_frames))

        frames = []
        for i in range(num_frames):
            offset = i * px_per_frame
            frame = Image.new("RGB", (screen_size, screen_size), bg_color)
            frame.paste(icon_img, (0, 0))
            frame.paste(text_surf.crop((offset, 0, offset + screen_size, text_height)), (0, icon_height))
            frames.append(frame)

        import logging as _logging
        icon_pixels = list(icon_img.getdata())
        icon_non_black = sum(1 for p in icon_pixels if p != (0, 0, 0))
        _logging.getLogger(__name__).debug(
            "icon+message GIF: screen=%d icon_height=%d text_height=%d "
            "frames=%d duration=%dms icon_non_black=%d/%d msg_w=%d",
            screen_size, icon_height, text_height,
            num_frames, frame_ms, icon_non_black, len(icon_pixels), text_width,
        )

        out = io.BytesIO()
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=frame_ms,
            loop=0,
            optimize=False,
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
