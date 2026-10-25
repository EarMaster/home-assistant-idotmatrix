"""Data update coordinator for iDotMatrix integration."""
from __future__ import annotations

import asyncio
import copy
import io
import logging
import math
import os
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from . import preview
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
    "last_message", "text_color", "text_font_size", "text_speed",
    "last_image", "last_image_kind",
    "icon_message_icon", "icon_message_text", "icon_message_text_color", "icon_message_icon_color",
    "scoreboard_home", "scoreboard_away",
    "countdown_minutes", "countdown_seconds", "countdown_timer_entity",
})


# Content settings captured before temporary content (restore_after) and put back
# afterwards, so e.g. a text notification doesn't replace the text that returns.
_RESTORE_KEYS = (
    "clock_style", "effect_mode",
    "last_message", "text_color", "text_font_size", "text_speed",
    "last_image", "last_image_kind",
    "icon_message_icon", "icon_message_text", "icon_message_text_color", "icon_message_icon_color",
    "scoreboard_home", "scoreboard_away", "countdown_minutes", "countdown_seconds",
)


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

# Spacing of writes that are downgraded to write-without-response (see _create_transport).
_WRITE_WITHOUT_RESPONSE_DELAY_S = 0.02

# Icon & Message animation: the device handles at most 64 GIF frames.
_GIF_MAX_FRAMES = 64
_PING_PONG_PAUSE_FRAMES = 6
_PING_PONG_MS_PER_PX = 70
_PING_PONG_MAX_FRAME_MS = 150
_TEXT_GLYPH_GAP_PX = 1
_TEXT_SPACE_PX = 3
_SCROLL_PADDING_PX = 2

# The device clock drifts and does not know about DST, so it is re-synced daily
# and whenever Home Assistant's UTC offset changes.
_TIME_RESYNC_INTERVAL = timedelta(hours=24)


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
        self._transport = None
        self._countdown_timer_unsub = None
        # Bumped whenever new content is shown; a scheduled restore only runs if
        # nothing else was shown since it was scheduled.
        self._content_generation = 0
        self._pending_restore: dict[str, Any] | None = None
        # Display Preview: exact pixels captured when they are sent (in memory only),
        # and the native-resolution GIF currently previewed.
        self._captured_preview: tuple[int, bytes] | None = None
        self._preview_key: tuple | None = None
        self.preview_native: bytes | None = None
        self.preview_version = dt_util.utcnow()
        self._clock_tick_unsub = None
        # UTC offset and time of the last successful time sync.
        self._time_synced_offset: timedelta | None = None
        self._time_synced_at = None
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
            "text_color": [255, 255, 255],
            "text_font_size": 24,
            "text_speed": 50,
            "last_image": "",
            "icon_message_icon": "mdi:information-outline",
            "icon_message_text": "",
            "last_image_kind": "file",
            # Stored as [r, g, b] so the action can use any color, not just presets.
            "icon_message_text_color": [255, 255, 255],
            "icon_message_icon_color": [255, 255, 255],
            "scoreboard_home": 0,
            "scoreboard_away": 0,
            "countdown_minutes": 0,
            "countdown_seconds": 0,
            "countdown_timer_entity": "",
        }

        from idotmatrix.client import IDotMatrixClient
        from idotmatrix.connection_manager import ConnectionListener
        from idotmatrix.screensize import ScreenSize

        screen_size_key = entry.data.get(CONF_SCREEN_SIZE, DEFAULT_SCREEN_SIZE)
        self.screen_size_px: int = int(screen_size_key.split("x")[0])
        self._client = IDotMatrixClient(
            screen_size=ScreenSize[SCREEN_SIZES[screen_size_key]],
            mac_address=self.mac_address,
            transport_factory=self._create_transport,
            # Home Assistant handles SIGINT/SIGTERM itself.
            install_signal_handlers=False,
        )
        self._client.add_connection_listener(
            ConnectionListener(on_connected=None, on_disconnected=self._async_on_disconnected)
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
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
            # 1.7.5–1.8.0 stored Icon & Message colors as preset names.
            for key in ("icon_message_text_color", "icon_message_icon_color"):
                if isinstance(self._state[key], str):
                    self._state[key] = list(COLOR_PRESETS.get(self._state[key], (255, 255, 255)))
            saved_timer = stored.get("countdown_timer_entity", "")
            if saved_timer:
                # Re-subscribe without triggering an immediate BLE command —
                # the device may not be connected yet at this point.
                self.hass.async_create_task(
                    self.async_set_countdown_timer(saved_timer, sync_now=False)
                )
        # The clock preview shows HA's time, so refresh it every minute in clock mode.
        @callback
        def _clock_tick(_now) -> None:
            if self._state.get("current_mode") == "clock":
                self.hass.async_create_task(self.async_request_refresh())

        self._clock_tick_unsub = async_track_time_change(self.hass, _clock_tick, second=0)
        try:
            await self._ble_connect()
        except Exception as ex:
            _LOGGER.info(
                "Initial connect to %s failed, will retry on next poll: %s",
                self.mac_address, ex,
            )

    def _create_transport(self, address_or_device, on_disconnected):
        """Library transport that connects through HA Bluetooth (local adapters and proxies)."""
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
        from idotmatrix.const import UUID_CHARACTERISTIC_WRITE_DATA
        from idotmatrix.transport import BleakTransport

        async def _connector(device, disconnected_callback):
            return await establish_connection(
                BleakClient, device, self.mac_address,
                disconnected_callback=disconnected_callback, max_attempts=3,
            )

        class _HaTransport(BleakTransport):
            async def write(self, data, response):
                # The library writes uploads with response, like the official app. If the
                # write characteristic only offers write-without-response (seen through an
                # ESPHome proxy), such writes fail with "Write not permitted" and drop the
                # connection, so downgrade them and space them out instead.
                if response:
                    char = self._client.services.get_characteristic(UUID_CHARACTERISTIC_WRITE_DATA)
                    if char is not None and "write" not in char.properties:
                        await super().write(data, response=False)
                        await asyncio.sleep(_WRITE_WITHOUT_RESPONSE_DELAY_S)
                        return
                await super().write(data, response)

        self._transport = _HaTransport(address_or_device, on_disconnected, connector=_connector)
        return self._transport

    async def _ble_connect(self) -> None:
        """Connect to the device via the BLEDevice that HA Bluetooth currently knows."""
        from homeassistant.components import bluetooth

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac_address, connectable=True
        ) or bluetooth.async_ble_device_from_address(
            self.hass, self.mac_address, connectable=False
        )
        if ble_device is None:
            raise ValueError(
                f"Device {self.mac_address} not found in HA Bluetooth scan cache"
            )

        self._client.set_ble_device(ble_device)
        await self._client.connect()
        self._connected = True
        self._state["is_on"] = True
        _LOGGER.info("Device %s connected", self.mac_address)
        self.hass.async_create_task(self.async_request_refresh())
        self.hass.async_create_task(self.async_sync_time())

    async def _async_on_disconnected(self) -> None:
        """Called by the library when the connection to the device is lost."""
        if self._connected:
            self._connected = False
            _LOGGER.info("Device %s disconnected", self.mac_address)
            await self.async_request_refresh()

    def _link_up(self) -> bool:
        """Whether the BLE link is up, according to the Bluetooth stack."""
        return self._transport is not None and self._transport.is_connected

    async def _async_reset_connection(self) -> None:
        """Forget a link that died without a disconnect callback, so the next connect starts fresh."""
        self._connected = False
        try:
            await self._client.disconnect()
        except Exception as ex:
            _LOGGER.debug("Error resetting the connection to %s: %s", self.mac_address, ex)

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
        elif self._time_synced_at is not None:
            now = dt_util.now()
            if (
                now.utcoffset() != self._time_synced_offset
                or now - self._time_synced_at >= _TIME_RESYNC_INTERVAL
            ):
                _LOGGER.debug("Re-syncing time on %s", self.mac_address)
                await self.async_sync_time()
        if self._state_dirty:
            self._state_dirty = False
            await self._store.async_save(
                {k: self._state[k] for k in _PERSIST_KEYS if k in self._state}
            )
        await self.async_update_preview()
        return self._state.copy()

    async def _async_send_command(self, command_func, *args, **kwargs) -> bool:
        """Execute a device command under the command lock, reconnecting first if needed."""
        if not self._connected or not self._link_up():
            if self._connected:
                # The link went down without firing the disconnect callback
                _LOGGER.debug("Stale BLE client detected for %s, reconnecting", self.mac_address)
                await self._async_reset_connection()
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
                if self._connected and not self._link_up():
                    await self._async_reset_connection()
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

    # Mode switching and temporary content

    def _set_current_mode(self, mode: str) -> None:
        """Record that new content of the given mode is on screen."""
        self._state["current_mode"] = mode
        self._content_generation += 1

    async def async_activate_mode(self, mode: str) -> bool:
        """Re-show the last content of a mode (what Display Mode does when selected)."""
        state = self._state
        if mode == "clock":
            return await self.async_set_clock_mode(
                CLOCK_STYLES[state.get("clock_style", _DEFAULT_CLOCK_STYLE)]
            )
        if mode == "text":
            return bool(state.get("last_message")) and await self.async_display_text(state["last_message"])
        if mode == "effect":
            return await self.async_display_effect(
                EFFECT_TYPES[state.get("effect_mode", _DEFAULT_EFFECT_MODE)]
            )
        if mode == "image":
            src = state.get("last_image", "")
            has_icon_msg = bool(state.get("icon_message_text"))
            if has_icon_msg and (state.get("last_image_kind") == "icon_message" or not src):
                return await self.async_display_icon_message()
            return bool(src) and await self.async_display_image(src)
        if mode == "chronograph":
            return await self.async_start_chronograph()
        if mode == "scoreboard":
            return await self.async_display_scoreboard(
                state.get("scoreboard_home", 0), state.get("scoreboard_away", 0)
            )
        if mode == "countdown":
            return await self.async_start_countdown(
                state.get("countdown_minutes", 0), state.get("countdown_seconds", 0)
            )
        return False

    def snapshot_for_restore(self) -> dict[str, Any]:
        """Capture what is on screen now, to bring it back after temporary content.

        If temporary content with a pending restore is still showing, its snapshot is
        reused, so back-to-back notifications all return to the original screen.
        """
        pending = self._pending_restore
        if pending and pending["generation"] == self._content_generation:
            return pending["snapshot"]
        return {
            "mode": self._state.get("current_mode", "clock"),
            "state": {k: copy.deepcopy(self._state[k]) for k in _RESTORE_KEYS if k in self._state},
        }

    def schedule_restore(self, snapshot: dict[str, Any], delay: timedelta) -> None:
        """Restore the snapshot after delay, unless other content is shown meanwhile."""
        self.cancel_pending_restore()
        generation = self._content_generation

        @callback
        def _restore(_now) -> None:
            self._pending_restore = None
            if self._content_generation == generation:
                self.hass.async_create_task(self._async_restore(snapshot))

        self._pending_restore = {
            "generation": generation,
            "snapshot": snapshot,
            "unsub": async_call_later(self.hass, delay, _restore),
        }

    def cancel_pending_restore(self) -> None:
        """Drop a scheduled restore (e.g. when a countdown is paused or stopped)."""
        if self._pending_restore is not None:
            self._pending_restore["unsub"]()
            self._pending_restore = None

    async def _async_restore(self, snapshot: dict[str, Any]) -> None:
        _LOGGER.debug("Restoring %s after temporary content", snapshot["mode"])
        self._state.update(copy.deepcopy(snapshot["state"]))
        await self.async_activate_mode(snapshot["mode"])
        await self.async_request_refresh()

    # Text

    async def async_display_text(
        self,
        message: str,
        font_size: int | None = None,
        color: list[int] | None = None,
        speed: int | None = None,
    ) -> bool:
        """Display a scrolling text message.

        Settings that are not given use the last ones (set via the show_text action),
        so Text: Message and Display Mode re-sends look the same as before.
        """
        if font_size is not None:
            self._state["text_font_size"] = font_size
        if color is not None:
            self._state["text_color"] = list(color)
        if speed is not None:
            self._state["text_speed"] = speed
        font_size = self._state["text_font_size"]
        color = tuple(self._state["text_color"])
        speed = self._state["text_speed"]
        font_path = self._text_font_path()
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
            self._set_current_mode("text")
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
            self._set_current_mode("clock")
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
        now = dt_util.now()
        success = await self._async_send_command(
            self._client.common.set_time, now.replace(tzinfo=None)
        )
        if success:
            self._time_synced_offset = now.utcoffset()
            self._time_synced_at = now
        return success

    # Effects

    async def async_display_effect(self, effect_type: int) -> bool:
        """Display a visual effect."""
        success = await self._async_send_command(
            self._client.effect.show,
            effect_type,
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        if success:
            self._set_current_mode("effect")
            self._state["effect_mode"] = _EFFECT_MODE_BY_ID.get(effect_type, _DEFAULT_EFFECT_MODE)
            self._fire_event("effect_displayed", {"effect_type": effect_type})
        return success

    # Image

    async def async_display_image(self, image_source: str, sharpen: bool = True) -> bool:
        """Display an image from a local file path or http(s) URL."""
        try:
            image_data = await self._fetch_image_data(image_source)
            is_gif, upload_data, native = await self.hass.async_add_executor_job(
                self._adapt_image, image_data, sharpen
            )
            if is_gif:
                # GIF upload uses its own command byte (1) which signals the device
                # to enter animation mode directly. Calling image.set_mode(EnableDIY)
                # first puts the device into static-image mode (command 0), which
                # causes it to ignore the subsequent GIF packets — leaving a black screen.
                success = await self._async_send_command(self._send_gif_blocks, upload_data)
            else:
                success = await self._upload_static_image(upload_data)
        except Exception as ex:
            _LOGGER.warning("Failed to display image %s: %s", image_source, ex)
            return False
        if success:
            self._set_current_mode("image")
            self._captured_preview = (self._content_generation, native)
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
        message = self._state.get("icon_message_text", "").strip()
        if not self._state.get("icon_message_icon", "").strip() or not message:
            _LOGGER.warning("Icon & Message needs both an icon and a text to display")
            return False
        try:
            gif_data = await self._async_build_icon_message_gif()
            # The GIF is already canvas-sized with a tiny palette, so it skips the
            # library's normalisation (which would also cap the animation at 2 s).
            success = await self._async_send_command(self._send_gif_blocks, gif_data)
        except Exception as ex:
            _LOGGER.warning("Failed to display icon+message: %s", ex)
            return False
        if success:
            self._set_current_mode("image")
            self._captured_preview = (self._content_generation, gif_data)
            self._state["last_image_kind"] = "icon_message"
            self._fire_event("image_displayed", {"message": message})
        return success

    async def _async_build_icon_message_gif(self) -> bytes:
        """Render the stored Icon & Message settings into the GIF sent to the device."""
        icon_source = self._state.get("icon_message_icon", "").strip()
        if icon_source.startswith("mdi:"):
            icon_data = await self._get_mdi_icon_bytes(
                icon_source[4:], tuple(self._state["icon_message_icon_color"])
            )
        else:
            icon_data = await self._fetch_image_data(icon_source)
        return await self.hass.async_add_executor_job(
            self._create_icon_message_gif,
            icon_data, self._state.get("icon_message_text", "").strip(), self.screen_size_px,
            tuple(self._state["icon_message_text_color"]), (0, 0, 0),
        )

    # Display Preview

    async def async_update_preview(self) -> None:
        """Re-render the preview if what is on screen may have changed."""
        mode = self._state.get("current_mode", "clock")
        now = dt_util.now()
        key = (
            self._content_generation,
            self._state.get("is_on", False),
            (now.hour, now.minute) if mode == "clock" else None,
        )
        if key == self._preview_key:
            return
        self._preview_key = key
        try:
            native = await self._async_render_preview(mode, now)
        except Exception as ex:
            _LOGGER.debug("Preview rendering failed for %s: %s", mode, ex)
            native = await self.hass.async_add_executor_job(preview.blank_gif, self.screen_size_px)
        if native != self.preview_native:
            self.preview_native = native
            self.preview_version = dt_util.utcnow()

    async def _async_render_preview(self, mode: str, now) -> bytes:
        """Native-resolution GIF approximating what the display shows right now."""
        size = self.screen_size_px
        state = self._state
        if not state.get("is_on", False):
            return await self.hass.async_add_executor_job(preview.blank_gif, size)
        captured = self._captured_preview
        if captured is not None and captured[0] == self._content_generation:
            return captured[1]
        if mode == "image":
            # Nothing captured yet (e.g. after a restart): rebuild from the stored settings.
            if state.get("last_image_kind") == "icon_message" and state.get("icon_message_text"):
                return await self._async_build_icon_message_gif()
            if state.get("last_image"):
                image_data = await self._fetch_image_data(state["last_image"])
                _, _, native = await self.hass.async_add_executor_job(self._adapt_image, image_data, True)
                return native
            return await self.hass.async_add_executor_job(preview.blank_gif, size)
        if mode == "text" and state.get("last_message"):
            font_path = self._text_font_path()
            return await self.hass.async_add_executor_job(
                preview.text_preview_gif, state["last_message"], font_path,
                state.get("text_font_size", 24), tuple(state.get("text_color", (255, 255, 255))), size,
            )
        icon, label, color = preview.fallback_spec(mode, state, now)
        icon_data = await self._get_mdi_icon_bytes(icon[4:], color)
        return await self.hass.async_add_executor_job(
            self._create_icon_message_gif, icon_data, label, size, color, (0, 0, 0)
        )

    async def async_update_icon_message(self, display: bool = False, **settings: str) -> bool:
        """Store Icon & Message settings, then display if asked to or if it is on screen.

        settings keys: icon, text, text_color, icon_color (colors as [r, g, b]).
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

    @staticmethod
    def _text_font_path() -> str:
        """Return the path to the text font that ships with the library."""
        import idotmatrix

        return os.path.join(os.path.dirname(idotmatrix.__file__), "fonts", "Rain-DRM3.otf")

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

    def _adapt_image(self, image_data: bytes, sharpen: bool) -> tuple[bool, bytes, bytes]:
        """Prepare image bytes for upload; also return the exact on-screen pixels.

        Returns (is_gif, upload_data, native_preview_gif). GIFs are normalised by the
        library (canvas size, palette, frame limit) and uploaded as-is; static images
        are uploaded as processed PNG and the library's own canvas adaptation is
        repeated here so the preview matches what it sends.
        """
        from idotmatrix.modules.image import ImageModule
        from idotmatrix.util.image_utils import ResizeMode

        size = self.screen_size_px
        if self._detect_gif(image_data):
            gif_data = self._client.gif._load_gif_and_adapt_to_canvas(
                io.BytesIO(image_data), size, ResizeMode.FIT, True, (0, 0, 0), None,
            )
            return True, gif_data, gif_data
        processed = self._process_static_image(image_data, sharpen)
        rgb = ImageModule._load_image_and_adapt_to_canvas(
            io.BytesIO(processed), size, ResizeMode.FIT, False, (0, 0, 0)
        )
        return False, processed, preview.rgb_to_gif(rgb, size)

    async def _upload_static_image(self, image_data: bytes) -> bool:
        """Upload static image bytes to the device."""
        ok = await self._async_send_command(self._client.image.set_mode)
        if not ok:
            return False
        return await self._async_send_command(
            self._client.image.upload_image_file, io.BytesIO(image_data)
        )

    async def _send_gif_blocks(self, gif_data: bytes) -> None:
        """Upload canvas-sized GIF bytes as they are and show them right away.

        Like the library's upload_gif_file(), minus its conversion: the GIF is already
        normalised (or rendered for the canvas), and the preview captures exactly these
        bytes. The device acknowledges every 4 KB block before the next one is sent.
        """
        from idotmatrix.util.device_material import INDEX_SHOW_NOW

        packets = self._client.gif.create_gif_data_packets(gif_data, gif_type=INDEX_SHOW_NOW, time_sign=0)
        _LOGGER.debug(
            "Uploading GIF to %s: %d bytes in %d block(s)", self.mac_address, len(gif_data), len(packets)
        )
        await self._client._connection_manager.send_packets(packets, response=True, wait_for_ack=True)

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
            self._set_current_mode("scoreboard")
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
            self._set_current_mode("countdown")
            self._state["countdown_minutes"] = minutes
            self._state["countdown_seconds"] = seconds
            self._fire_event("countdown_started", {"minutes": minutes, "seconds": seconds})
        return success

    async def async_pause_countdown(self) -> bool:
        """Pause the running countdown."""
        success = await self._async_send_command(self._client.countdown.pause)
        if success:
            self.cancel_pending_restore()
            self._fire_event("countdown_paused")
        return success

    async def async_stop_countdown(self) -> bool:
        """Stop (disable) the countdown."""
        success = await self._async_send_command(self._client.countdown.stop)
        if success:
            self.cancel_pending_restore()
            self._fire_event("countdown_stopped")
        return success

    async def async_restart_countdown(self) -> bool:
        """Restart the countdown from its original duration."""
        success = await self._async_send_command(self._client.countdown.restart)
        if success:
            self._set_current_mode("countdown")
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
            self._set_current_mode("chronograph")
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
        self.cancel_pending_restore()
        if self._clock_tick_unsub is not None:
            self._clock_tick_unsub()
            self._clock_tick_unsub = None
        if self._countdown_timer_unsub is not None:
            self._countdown_timer_unsub()
            self._countdown_timer_unsub = None
        _LOGGER.info("Shutting down iDotMatrix coordinator for %s", self.mac_address)
        self._connected = False
        try:
            await self._client.disconnect()
        except Exception as ex:
            _LOGGER.debug("Error during shutdown disconnect: %s", ex)
