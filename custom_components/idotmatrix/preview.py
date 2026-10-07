"""Rendering helpers for the Display Preview image entity.

The device is write-only, so the preview is derived from what the integration sends:
exact pixels for images and Icon & Message (captured at send time by the coordinator),
an approximation for scrolling text (the library draws glyphs on the host, the device
scrolls them), and a labelled fallback (icon + live value) for modes the device draws
itself. All functions are blocking (Pillow) and must run in the executor.
"""
from __future__ import annotations

import io
import math
from datetime import datetime
from typing import Any

from .const import COLOR_PRESETS

PREVIEW_TARGET_PX = 320  # upscaled output size (approx.; 16/32/64 px → ×20/×10/×5)
_GIF_MAX_FRAMES = 64

# Library text glyph cells (idotmatrix/modules/text.py): 16×32, regardless of screen size.
_GLYPH_W = 16
_GLYPH_H = 32
_MARQUEE_MS_PER_PX = 40
_MARQUEE_MAX_FRAME_MS = 150

_WHITE = (255, 255, 255)


def _save_gif(frames: list, durations: list[int] | int) -> bytes:
    out = io.BytesIO()
    frames[0].save(
        out, format="GIF", save_all=True, append_images=frames[1:],
        duration=durations, loop=0, disposal=2,
    )
    return out.getvalue()


def blank_gif(size: int) -> bytes:
    """A single black frame (display off, or nothing known)."""
    from PIL import Image

    return _save_gif([Image.new("RGB", (size, size), (0, 0, 0))], 1000)


def rgb_to_gif(rgb: bytes | bytearray, size: int) -> bytes:
    """Single-frame GIF from the raw RGB buffer the library uploads for static images."""
    from PIL import Image

    return _save_gif([Image.frombytes("RGB", (size, size), bytes(rgb))], 1000)


def upscale_gif(native_gif: bytes, factor: int) -> bytes:
    """Nearest-neighbour upscale of every frame, keeping per-frame durations.

    Browsers smooth small images when stretching them, so the entity serves the
    preview already enlarged with sharp pixels.
    """
    from PIL import Image, ImageSequence

    src = Image.open(io.BytesIO(native_gif))
    frames, durations = [], []
    for frame in ImageSequence.Iterator(src):
        rgb = frame.convert("RGB")
        frames.append(rgb.resize((rgb.width * factor, rgb.height * factor), Image.NEAREST))
        durations.append(int(frame.info.get("duration", 100)) or 100)
    return _save_gif(frames, durations if len(durations) > 1 else durations[0])


def upscale_factor(size: int) -> int:
    return max(1, PREVIEW_TARGET_PX // size)


def text_preview_gif(message: str, font_path: str, font_size: int, color: tuple, size: int) -> bytes:
    """Approximate the device's scrolling text.

    Glyphs are drawn exactly like the library does before sending them (16×32 "1"-mode
    cell per character, centred with textbbox); the scrolling itself happens on the
    device, so the marquee here is an approximation. For 16×16 / 64×64 screens the
    glyph strip is scaled to the screen height.
    """
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, font_size)
    strip = Image.new("1", (max(1, _GLYPH_W * len(message)), _GLYPH_H), 0)
    for index, char in enumerate(message):
        cell = Image.new("1", (_GLYPH_W, _GLYPH_H), 0)
        draw = ImageDraw.Draw(cell)
        # Same (quirky) centring as the library: it treats bbox right/bottom as size.
        _, _, text_width, text_height = draw.textbbox((0, 0), text=char, font=font)
        draw.text(((_GLYPH_W - text_width) // 2, (_GLYPH_H - text_height) // 2), char, fill=1, font=font)
        strip.paste(cell, (index * _GLYPH_W, 0))

    if size != _GLYPH_H:
        scale = size / _GLYPH_H
        strip = strip.resize((max(1, round(strip.width * scale)), size), Image.NEAREST)
    mask = strip.convert("L")
    colored = Image.new("RGB", mask.size, (0, 0, 0))
    colored.paste(color, mask=mask)

    # Marquee: enter from the right edge, scroll until fully gone.
    travel = size + colored.width
    step = max(1, math.ceil(travel / _GIF_MAX_FRAMES))
    frame_ms = min(_MARQUEE_MAX_FRAME_MS, _MARQUEE_MS_PER_PX * step)
    y = (size - colored.height) // 2
    frames = []
    for offset in range(0, travel, step):
        frame = Image.new("RGB", (size, size), (0, 0, 0))
        frame.paste(colored, (size - offset, y))
        frames.append(frame)
    return _save_gif(frames, frame_ms)


def fallback_spec(mode: str, state: dict[str, Any], now: datetime) -> tuple[str, str, tuple]:
    """Icon, label and color for modes the device draws itself.

    Kept in one place so per-size reference templates can replace it later.
    """
    if mode == "clock":
        if state.get("clock_hour24", True):
            label = f"{now.hour:02d}:{now.minute:02d}"
        else:
            label = f"{(now.hour % 12) or 12}:{now.minute:02d}"
        color = COLOR_PRESETS.get(state.get("clock_color", "white"), _WHITE)
        return "mdi:clock-outline", label, color
    if mode == "scoreboard":
        return "mdi:scoreboard", f"{state.get('scoreboard_home', 0)}:{state.get('scoreboard_away', 0)}", _WHITE
    if mode == "countdown":
        return (
            "mdi:timer-sand",
            f"{state.get('countdown_minutes', 0):02d}:{state.get('countdown_seconds', 0):02d}",
            _WHITE,
        )
    if mode == "chronograph":
        return "mdi:timer-outline", "Stopwatch", _WHITE
    if mode == "effect":
        return "mdi:auto-fix", str(state.get("effect_mode", "Effect")), _WHITE
    return "mdi:help-rhombus-outline", mode or "?", _WHITE
