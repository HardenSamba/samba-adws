import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple


class SubscriptionCache:

    MAX_SUBSCRIPTIONS = 256
    DEFAULT_TTL_SECONDS = 3600

    def __init__(self) -> None:
        self._entries: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def create(self, ttl_seconds: Optional[int] = None) -> Tuple[str, datetime]:
        ttl = ttl_seconds or self.DEFAULT_TTL_SECONDS
        sub_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        with self._lock:
            if len(self._entries) >= self.MAX_SUBSCRIPTIONS:
                oldest = min(self._entries, key=lambda k: self._entries[k])
                del self._entries[oldest]
            self._entries[sub_id] = expires_at
        return sub_id, expires_at

    def renew(self, sub_id: str, ttl_seconds: Optional[int] = None) -> Optional[datetime]:
        ttl = ttl_seconds or self.DEFAULT_TTL_SECONDS
        with self._lock:
            if sub_id not in self._entries:
                return None
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)
            self._entries[sub_id] = expires_at
        return expires_at

    def get_expires(self, sub_id: str) -> Optional[datetime]:
        with self._lock:
            return self._entries.get(sub_id)

    def remove(self, sub_id: str) -> bool:
        with self._lock:
            return self._entries.pop(sub_id, None) is not None
