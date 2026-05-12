"""Constants for the iDotMatrix integration."""
from __future__ import annotations

DOMAIN = "idotmatrix"

# Configuration
CONF_DEVICE_NAME = "device_name"
CONF_MAC_ADDRESS = "mac_address"
CONF_SCREEN_SIZE = "screen_size"

# Default values
DEFAULT_NAME = "iDotMatrix Display"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_SCREEN_SIZE = "32x32"

# Platforms
PLATFORMS = ["light", "switch", "text", "select", "button"]

# Screen sizes (display label → ScreenSize enum member name)
SCREEN_SIZES = {
    "16x16": "SIZE_16x16",
    "32x32": "SIZE_32x32",
    "64x64": "SIZE_64x64",
}

# Services
SERVICE_DISPLAY_TEXT = "display_text"
SERVICE_DISPLAY_IMAGE = "display_image"
SERVICE_SET_CLOCK_MODE = "set_clock_mode"
SERVICE_DISPLAY_EFFECT = "display_effect"
SERVICE_SYNC_TIME = "sync_time"

# Service attributes
ATTR_MESSAGE = "message"
ATTR_FONT_SIZE = "font_size"
ATTR_COLOR = "color"
ATTR_SPEED = "speed"
ATTR_IMAGE_PATH = "image_path"
ATTR_CLOCK_STYLE = "clock_style"
ATTR_EFFECT_TYPE = "effect_type"
ATTR_DURATION = "duration"

# Clock styles — matches ClockStyle enum in idotmatrix>=0.1.0
CLOCK_STYLES = {
    "RGB Swipe Outline": 0,
    "Christmas Tree": 1,
    "Checkers": 2,
    "Color": 3,
    "Hourglass": 4,
    "Alarm Clock": 5,
    "Outlines": 6,
    "RGB Corners": 7,
}

# Effect types — matches EffectStyle enum in idotmatrix>=0.1.0 (integers 0–6)
EFFECT_TYPES = {
    "Horizontal Rainbow": 0,
    "Random Colored Pixels": 1,
    "White on Changing BG": 2,
    "Vertical Rainbow": 3,
    "Diagonal Right Rainbow": 4,
    "Diagonal Left Rainbow": 5,
    "Random Colored": 6,
}

# Font sizes
FONT_SIZES = {
    "small": 8,
    "medium": 12,
    "large": 16,
}

# Color presets
COLOR_PRESETS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "white": (255, 255, 255),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 192, 203),
}
