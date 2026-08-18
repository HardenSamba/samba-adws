import threading
from typing import Dict, Optional, Union

DEFAULT_LIMITS: Dict[str, int] = {
    "max_sessions": 10,
    "max_enumeration_contexts": 50,
    "max_concurrent_calls": 25,
}


class QuotaLedger:

    def __init__(self, limits: Optional[Dict[str, int]] = None) -> None:
        self._lock = threading.RLock()
        self._counters: Dict[str, Dict[str, int]] = {}
        self.limits: Dict[str, int] = dict(DEFAULT_LIMITS)
        if limits:
            self.limits.update(limits)

    def increment(self, owner: str, resource: str) -> int:
        limit = self.limits.get(resource)
        with self._lock:
            counters = self._counters.setdefault(owner, {})
            current = counters.get(resource, 0)
            if limit is not None and current >= limit:
                raise RuntimeError(
                    f"Quota exceeded for {owner} on {resource} (limit {limit})"
                )
            counters[resource] = current + 1
            return counters[resource]

    def decrement(self, owner: str, resource: str) -> None:
        with self._lock:
            counters = self._counters.get(owner, {})
            if resource in counters and counters[resource] > 0:
                counters[resource] -= 1

    def snapshot(
        self, owner: Optional[str] = None
    ) -> Union[Dict[str, int], Dict[str, Dict[str, int]]]:
        with self._lock:
            if owner is not None:
                return dict(self._counters.get(owner, {}))
            return {k: dict(v) for k, v in self._counters.items()}

    def reset(self, owner: Optional[str] = None) -> None:
        with self._lock:
            if owner is None:
                self._counters.clear()
            else:
                self._counters.pop(owner, None)
