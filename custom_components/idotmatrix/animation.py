"""Animated content for the device: LaMetric icons and GIF frame timelines.

A timeline is a looping list of ``(duration_ms, value)`` segments. Icon & Message
combines two of them (icon frames and text scroll positions) into one GIF loop in which
both restart cleanly. The Pillow functions are blocking and must run in the executor.
"""
from __future__ import annotations

import bisect
import io
import re
from typing import Any

LAMETRIC_PREFIX = "lam:"
# Public, unauthenticated endpoint (also used by AWTRIX); serves 8×8 GIF or PNG.
LAMETRIC_ICON_URL = "https://developer.lametric.com/content/apps/icon_thumbs/{}"

# The device handles at most 64 GIF frames.
GIF_MAX_FRAMES = 64
# GIF frame delays are stored in 1/100 s.
_GIF_TICK_MS = 10
_MIN_FRAME_MS = 20
# Fitting the text loop to the icon loop shortens its pauses no further than this.
_MIN_PAUSE_MS = 300
_DEFAULT_FRAME_MS = 100

Timeline = list[tuple[float, Any]]


def is_lametric(source: str) -> bool:
    return source.strip().lower().startswith(LAMETRIC_PREFIX)


def lametric_icon_id(source: str) -> str:
    """Return the icon id of a ``lam:<id>`` source."""
    icon_id = source.strip()[len(LAMETRIC_PREFIX):].strip()
    if not re.fullmatch(r"[0-9]+", icon_id):
        raise ValueError(f"Invalid LaMetric icon {source!r}: expected lam:<number>, e.g. lam:18391")
    return icon_id


# Pillow


def load_frames(image_data: bytes, bg_color: tuple) -> Timeline:
    """Decode a still or animated image into RGB frames on bg_color, as a timeline.

    A still image is a single segment; consecutive identical GIF frames are merged.
    """
    from PIL import Image, ImageOps, ImageSequence

    src = Image.open(io.BytesIO(image_data))
    if getattr(src, "n_frames", 1) == 1:
        try:
            src = ImageOps.exif_transpose(src)
        except Exception:
            pass
    timeline = []
    for frame in ImageSequence.Iterator(src):
        rgba = frame.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, bg_color)
        rgb.paste(rgba, mask=rgba.split()[-1])
        timeline.append((int(frame.info.get("duration") or _DEFAULT_FRAME_MS), rgb))
    return _merge_repeats(timeline, key=lambda img: img.tobytes())


def fit_image(img, box_w: int, box_h: int):
    """Fit an image into a box without distorting it.

    Smaller images are enlarged by a whole factor with nearest-neighbour, so pixel art
    (e.g. 8×8 LaMetric icons) stays crisp; larger ones are shrunk smoothly and sharpened.
    """
    from PIL import Image, ImageFilter

    if img.width <= box_w and img.height <= box_h:
        factor = min(box_w // img.width, box_h // img.height)
        if factor > 1:
            return img.resize((img.width * factor, img.height * factor), Image.NEAREST)
        return img
    img = img.copy()
    img.thumbnail((box_w, box_h), Image.LANCZOS)
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))


def save_gif(frames: list, durations: list[int]) -> bytes:
    """Encode RGB frames as a looping GIF the device accepts."""
    from PIL import Image

    # Same palette conversion as the library's GIF normalisation.
    frames = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for f in frames]
    # Same encoder settings as the library: it notes optimize=False breaks uploads.
    out = io.BytesIO()
    frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations if len(durations) > 1 else durations[0],
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out.getvalue()


def fullscreen_gif(image_data: bytes, size: int) -> bytes:
    """Render a (LaMetric) pixel-art image centred on the whole canvas."""
    from PIL import Image

    frames = load_frames(image_data, (0, 0, 0))
    timeline = prune([(ms, i) for i, (ms, _) in enumerate(frames)])
    if len(timeline) == 1:
        timeline = [(1000, timeline[0][1])]
    images = []
    for _, i in timeline:
        icon = fit_image(frames[i][1], size, size)
        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        canvas.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2))
        images.append(canvas)
    return save_gif(images, [int(ms) for ms, _ in timeline])


# Timelines


def cycle_ms(timeline: Timeline) -> float:
    return sum(ms for ms, _ in timeline)


def fit_cycle(timeline: Timeline, target_ms: float, pauses: tuple[int, ...] = ()) -> Timeline:
    """Change a timeline's loop length to target_ms.

    The difference goes into the pause segments first, so scrolling keeps its speed;
    pauses shrink to _MIN_PAUSE_MS at most, and only what's left changes the speed.
    """
    durations = [ms for ms, _ in timeline]
    delta = target_ms - sum(durations)
    if pauses and delta >= 0:
        for i in pauses:
            durations[i] += delta / len(pauses)
        delta = 0
    elif pauses:
        spare = {i: max(0.0, durations[i] - _MIN_PAUSE_MS) for i in pauses}
        total_spare = sum(spare.values())
        taken = min(-delta, total_spare)
        for i in pauses:
            if total_spare:
                durations[i] -= taken * spare[i] / total_spare
        delta += taken
    if delta:
        scalable = [i for i in range(len(durations)) if i not in pauses] or list(range(len(durations)))
        scalable_ms = sum(durations[i] for i in scalable)
        for i in scalable:
            durations[i] *= (scalable_ms + delta) / scalable_ms
    return [(ms, value) for ms, (_, value) in zip(durations, timeline)]


def combine(icon: Timeline, text: Timeline, text_pauses: tuple[int, ...] = ()) -> Timeline:
    """Play the icon and text loops together in one GIF loop of at most 64 frames.

    Both have to restart cleanly when the GIF loops, so the GIF loop is a whole number
    of icon loops and of text loops: the shorter loop repeats as often as best fits the
    longer one, and the text loop is fitted to that length (see fit_cycle). Returns
    segments whose value is ``(icon_value, text_value)``.
    """
    icon_ms, text_ms = cycle_ms(icon), cycle_ms(text)
    icon_reps = text_reps = 1
    if len(icon) == 1:
        icon = [(text_ms, icon[0][1])]
    elif len(text) == 1:
        text = [(icon_ms, text[0][1])]
    elif text_ms >= icon_ms:
        icon_reps = max(1, round(text_ms / icon_ms))
        text = fit_cycle(text, icon_reps * icon_ms, text_pauses)
    else:
        text_reps = max(1, round(icon_ms / text_ms))
        text = fit_cycle(text, icon_ms / text_reps, text_pauses)
    loop_ms = _to_tick(cycle_ms(icon) * icon_reps)

    icon_starts, icon_values = _starts(icon, icon_reps)
    text_starts, text_values = _starts(text, text_reps)
    starts = sorted({t for t in icon_starts + text_starts if t < loop_ms})
    segments = []
    for start, end in zip(starts, starts[1:] + [loop_ms]):
        icon_value = icon_values[bisect.bisect_right(icon_starts, start) - 1]
        text_value = text_values[bisect.bisect_right(text_starts, start) - 1]
        segments.append((end - start, (icon_value, text_value)))
    return prune(_merge_repeats(segments))


def prune(timeline: Timeline, max_frames: int = GIF_MAX_FRAMES) -> Timeline:
    """Drop the shortest frames until the loop fits the device's frame limit.

    A dropped frame's time goes to the frame before it, so near-simultaneous icon and
    text changes collapse into one frame first.
    """
    timeline = [[ms, value] for ms, value in timeline]
    while len(timeline) > 1 and (
        len(timeline) > max_frames or min(ms for ms, _ in timeline) < _MIN_FRAME_MS
    ):
        i = min(range(len(timeline)), key=lambda k: timeline[k][0])
        timeline[i - 1][0] += timeline[i][0]  # i - 1 is the last frame when i == 0
        del timeline[i]
        timeline = [list(s) for s in _merge_repeats(timeline)]
    return [(ms, value) for ms, value in timeline]


def _to_tick(ms: float) -> int:
    return int(round(ms / _GIF_TICK_MS)) * _GIF_TICK_MS


def _starts(timeline: Timeline, reps: int) -> tuple[list[int], list[Any]]:
    """Start times (rounded to GIF ticks) and values of each segment over reps loops."""
    starts, values, t = [], [], 0.0
    for _ in range(reps):
        for ms, value in timeline:
            tick = _to_tick(t)
            if starts and starts[-1] == tick:
                values[-1] = value
            else:
                starts.append(tick)
                values.append(value)
            t += ms
    return starts, values


def _merge_repeats(timeline, key=lambda value: value) -> Timeline:
    """Merge consecutive segments with the same value."""
    merged: list = []
    for ms, value in timeline:
        if merged and key(merged[-1][1]) == key(value):
            merged[-1] = (merged[-1][0] + ms, merged[-1][1])
        else:
            merged.append((ms, value))
    return merged
