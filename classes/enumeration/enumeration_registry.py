import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from classes.enumeration.enumeration_context import EnumerationContext


class EnumerationRegistry:

    MAX_CONTEXTS = 256
    MAX_RESULTS_PER_CONTEXT = 50000

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._cache: Dict[str, EnumerationContext] = {}

    def create_context(
        self,
        base_dn: str,
        search_filter: str,
        attributes: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> str:
        if len(self._cache) >= self.MAX_CONTEXTS:
            oldest_id = min(self._cache, key=lambda k: self._cache[k].created_at)
            self.logger.warning(f"[ENUM] Cache full, evicting {oldest_id}")
            del self._cache[oldest_id]
        ctx_id = str(uuid.uuid4())
        now = datetime.utcnow()
        self._cache[ctx_id] = EnumerationContext(
            context_id=ctx_id, created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            base_dn=base_dn, search_filter=search_filter,
            attributes=attributes or [], session_id=session_id,
        )
        self.logger.info(
            f"[ENUM] Created context {ctx_id} for {base_dn} (TTL: {ttl_seconds}s)"
        )
        return ctx_id

    def get_context(self, ctx_id: str) -> Optional[EnumerationContext]:
        ctx = self._cache.get(ctx_id)
        if ctx and ctx.is_expired:
            self.logger.info(f"[ENUM] Context {ctx_id} has expired, removing")
            del self._cache[ctx_id]
            return None
        return ctx

    def release_context(self, ctx_id: str) -> bool:
        if ctx_id in self._cache:
            del self._cache[ctx_id]
            self.logger.info(f"[ENUM] Released context {ctx_id}")
            return True
        return False

    def renew_context(self, ctx_id: str, ttl_seconds: int = 3600) -> bool:
        ctx = self.get_context(ctx_id)
        if ctx is None:
            return False
        ctx.expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        return True
