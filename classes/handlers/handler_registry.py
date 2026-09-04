import logging
from typing import Any, Dict, List, Optional

from src.handlers.handler_routing import ACTION_HANDLER_KEYS, HANDLER_FACTORIES

from classes.handlers import BaseHandler


class HandlerRegistry:

    def __init__(self, logger: logging.Logger, session_info: Any = None) -> None:
        self._handlers: Dict[str, BaseHandler] = {
            key: cls(logger, session_info) for key, cls in HANDLER_FACTORIES
        }

    def resolve(self, action_url: str) -> Optional[BaseHandler]:
        if not action_url:
            return None
        normalized = action_url.lower()
        key = ACTION_HANDLER_KEYS.get(normalized)
        if key:
            return self._handlers.get(key)
        suffix = action_url.rsplit("/", 1)[-1]
        return self._handlers.get(suffix)

    def keys(self) -> List[str]:
        return list(self._handlers.keys())
