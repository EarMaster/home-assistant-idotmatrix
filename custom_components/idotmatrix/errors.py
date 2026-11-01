"""Errors shown to the user, with messages from the translations' "exceptions" section."""
from __future__ import annotations

import difflib
import re

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

# Source prefixes the integration understands, used to suggest a fix for typos.
_KNOWN_PREFIXES = ("lam", "mdi", "http", "https")


class DisplayError(HomeAssistantError):
    """Content could not be shown; the message says why and how to fix it."""

    def __init__(self, key: str, **placeholders: object) -> None:
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={k: str(v) for k, v in placeholders.items()},
        )


def source_not_found(source: str) -> DisplayError:
    """Error for an image source that is neither a known prefix nor an existing file."""
    if match := re.match(r"([A-Za-z]{2,6}):(.*)", source):
        prefix, rest = match.groups()
        close = difflib.get_close_matches(prefix.lower(), _KNOWN_PREFIXES, n=1, cutoff=0.5)
        if close:
            return DisplayError("image_source_typo", source=source, suggestion=f"{close[0]}:{rest}")
    return DisplayError("image_not_found", source=source)
