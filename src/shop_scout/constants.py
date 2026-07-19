"""Stable project constants."""

from typing import Final

DEFAULT_VISION_VARIANT: Final = "original"
TRACKING_QUERY_KEYS: Final = frozenset(
    {"spm", "scm", "pvid", "abbucket", "utm_source", "utm_medium", "utm_campaign"}
)
