import threading
import time
from typing import Any, Dict, Optional, Tuple


class SchemaCache:

    DEFAULT_TTL: int = 600

    def __init__(self) -> None:
        self._entries: Dict[str, Tuple[Any, float]] = {}
        self._lock: threading.Lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl or self.DEFAULT_TTL
        with self._lock:
            self._entries[key] = (value, time.time() + ttl)

    def invalidate(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)
