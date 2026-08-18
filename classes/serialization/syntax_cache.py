import threading
import time
from typing import Any

import ldb

from classes.serialization.syntaxes import SyntaxRegistry

DEFAULT_TTL_SECONDS: int = 3600


class SyntaxCache:

    def __init__(self, samdb: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.samdb: Any = samdb
        self.ttl_seconds: int = ttl_seconds
        self._registry: SyntaxRegistry = SyntaxRegistry()
        self._loaded_at: float = 0
        self._lock: threading.RLock = threading.RLock()

    def registry(self) -> SyntaxRegistry:
        with self._lock:
            if (time.time() - self._loaded_at) > self.ttl_seconds:
                self._reload_unlocked()
            return self._registry

    def _reload_unlocked(self) -> None:
        try:
            schema_dn = self._schema_dn()
            results = self.samdb.search(
                base=schema_dn, scope=ldb.SCOPE_ONELEVEL,
                expression="(objectClass=attributeSchema)",
                attrs=["lDAPDisplayName", "attributeSyntax"],
            )
            for msg in results:
                self._register_one(msg)
            self._loaded_at = time.time()
        except Exception:
            self._loaded_at = time.time()

    def _schema_dn(self) -> str:
        result = self.samdb.search(base="", scope=ldb.SCOPE_BASE, attrs=["schemaNamingContext"])
        if not result or "schemaNamingContext" not in result[0]:
            raise RuntimeError("schemaNamingContext not found")
        raw = result[0]["schemaNamingContext"][0]
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def _register_one(self, msg: Any) -> None:
        if "lDAPDisplayName" not in msg or "attributeSyntax" not in msg:
            return
        name_raw = msg["lDAPDisplayName"][0]
        oid_raw = msg["attributeSyntax"][0]
        name = name_raw.decode("utf-8") if isinstance(name_raw, bytes) else str(name_raw)
        oid = oid_raw.decode("utf-8") if isinstance(oid_raw, bytes) else str(oid_raw)
        self._registry.register(name, oid)
