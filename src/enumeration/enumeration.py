import logging
from typing import Optional

from classes.enumeration.enumeration_registry import EnumerationRegistry

_INSTANCE: Optional[EnumerationRegistry] = None


def get_enumeration_registry(logger: logging.Logger) -> EnumerationRegistry:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = EnumerationRegistry(logger)
    return _INSTANCE
