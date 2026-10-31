"""Text fonts a device can use, and the size each is drawn at.

Pixel fonts only look sharp at sizes where one font pixel is a whole number of
LEDs, so every font lists those sizes; the size used is the largest of them that
fits the space. Fonts without a pixel grid (Rain DRM3) can use any size.
"""
from __future__ import annotations

import functools
import os
from dataclasses import dataclass

_BUNDLED = os.path.join(os.path.dirname(__file__), "fonts")

# Glyphs that set how tall a font's ink gets: accented capitals and descenders,
# and the same without accents (accents may be clipped when nothing else fits).
_INK_FULL = "ÄÅÉgjpqy"
_INK_CORE = "Hgjpqy"
_INK_WIDE = "MW@m"
# Text mode sends every character as a bitmap of at most 16x32 pixels.
_TEXT_CELL = (16, 32)
# Sizes tried for fonts without a pixel grid, and as the last resort for others.
_ANY_SIZE = range(4, 65)


@dataclass(frozen=True)
class Face:
    """A font file at one size; px is the LED width of one font pixel."""

    path: str
    size: int
    px: int


def _library(name: str) -> str:
    """Path of a font that ships with the idotmatrix library."""
    import idotmatrix

    return os.path.join(os.path.dirname(idotmatrix.__file__), "fonts", name)


def _scaled(path: str, unit: int) -> tuple[Face, ...]:
    """Sharp sizes of a pixel font designed on a grid of ``unit`` pixels."""
    return tuple(Face(path, unit * k, k) for k in range(1, 9))


def _faces(name: str) -> tuple[Face, ...]:
    if name == "Press Start 2P":
        return _scaled(_library("16-PressStart2P-Regular.ttf"), 8)
    if name == "Tiny5":
        return _scaled(os.path.join(_BUNDLED, "Tiny5-Regular.ttf"), 8)
    if name == "Cozette":
        return _scaled(os.path.join(_BUNDLED, "CozetteVector.ttf"), 13)
    if name == "Spleen":
        # A hand-drawn bitmap per size; 5x8 covers ASCII only.
        return tuple(
            Face(os.path.join(_BUNDLED, f"spleen-{w}x{h}.{ext}"), h, 2 if h >= 24 else 1)
            for w, h, ext in ((5, 8, "otb"), (6, 12, "otf"), (8, 16, "otf"), (12, 24, "otf"), (16, 32, "otf"))
        )
    path = _library("Rain-DRM3.otf")
    return tuple(Face(path, size, max(1, round(size / 12))) for size in _ANY_SIZE)


FONTS = ("Press Start 2P", "Tiny5", "Cozette", "Rain DRM3", "Spleen")
DEFAULT_FONT = FONTS[0]

# Characters Press Start 2P lacks, replaced by their closest look-alikes.
SUBSTITUTES = str.maketrans({"Ș": "Ş", "ș": "ş", "Ț": "Ţ", "ț": "ţ", "ẞ": "SS"})


@functools.lru_cache(maxsize=64)
def load(face: Face):
    """The Pillow font for a face."""
    from PIL import ImageFont

    return ImageFont.truetype(face.path, face.size)


def _box(face: Face, text: str) -> tuple[int, int, int, int]:
    from PIL import Image, ImageDraw

    return ImageDraw.Draw(Image.new("1", (1, 1))).textbbox((0, 0), text, font=load(face))


def _height(face: Face, text: str) -> int:
    box = _box(face, text)
    return box[3] - box[1]


@functools.lru_cache(maxsize=64)
def strip_face(name: str, height: int) -> tuple[Face, int]:
    """Face for a text strip ``height`` pixels tall, and the y to draw it at.

    Prefers the largest sharp size that fits accents and descenders, then one where
    only accents get clipped, then any size that fits.
    """
    faces = _faces(name if name in FONTS else DEFAULT_FONT)
    for ref in (_INK_FULL, _INK_CORE):
        fitting = [f for f in faces if _height(f, ref) <= height]
        if fitting:
            face = fitting[-1]
            break
    else:
        path = faces[0].path
        fitting = [Face(path, s, 1) for s in _ANY_SIZE if _height(Face(path, s, 1), _INK_FULL) <= height]
        face, ref = (fitting[-1] if fitting else Face(path, _ANY_SIZE[0], 1)), _INK_FULL
    # Centre the reference ink; the same y for every glyph keeps a common baseline.
    box = _box(face, ref)
    return face, (height - (box[3] - box[1])) // 2 - box[1]


@functools.lru_cache(maxsize=64)
def text_mode_face(name: str, font_size: int) -> Face:
    """Face for the device's text mode: the largest sharp size up to ``font_size``
    whose glyphs fit the device's character cell.

    Rain DRM3 has no pixel grid and is used at exactly ``font_size``, as before fonts
    were selectable.
    """
    if name == "Rain DRM3":
        return Face(_library("Rain-DRM3.otf"), font_size, 1)
    faces = [
        f for f in _faces(name if name in FONTS else DEFAULT_FONT)
        if max(_box(f, c)[2] for c in _INK_WIDE) <= _TEXT_CELL[0] and _height(f, _INK_FULL) <= _TEXT_CELL[1]
    ]
    fitting = [f for f in faces if f.size <= font_size]
    return fitting[-1] if fitting else faces[0]
