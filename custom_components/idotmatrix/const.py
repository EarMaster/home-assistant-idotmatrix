"""Constants for the iDotMatrix integration."""
from __future__ import annotations

DOMAIN = "idotmatrix"

# Configuration
CONF_DEVICE_NAME = "device_name"
CONF_MAC_ADDRESS = "mac_address"

# Default values
DEFAULT_NAME = "iDotMatrix Display"
DEFAULT_SCAN_INTERVAL = 30

# Platforms
PLATFORMS = ["light", "switch", "text", "select", "button"]

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

# Clock styles mapping
CLOCK_STYLES = {
    "classic": 0,
    "digital": 1,
    "analog": 2,
    "minimal": 3,
    "colorful": 4,
}

# Effect types mapping
EFFECT_TYPES = {
    "rainbow": 0,
    "breathing": 1,
    "wave": 2,
    "fire": 3,
    "snow": 4,
    "matrix": 5,
    "stars": 6,
    "plasma": 7,
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

# Device connection constants
SCAN_TIMEOUT = 10
CONNECTION_TIMEOUT = 30
RECONNECT_INTERVAL = 60
MAX_RETRIES = 3
