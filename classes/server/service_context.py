import threading
from typing import Any, Dict

from classes.directory.instance_index import InstanceIndex
from classes.directory.ldap_session_pool import LdapSessionPool
from classes.directory.quota_ledger import QuotaLedger


class ServiceContext:

    _instance: "ServiceContext | None" = None
    _lock = threading.Lock()

    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self.quotas: Any = QuotaLedger()
        self.instances: InstanceIndex = InstanceIndex()
        self.session_pool: Any = LdapSessionPool(logger)
        self.syntax_caches: Dict[int, Any] = {}

    @classmethod
    def get(cls, logger: Any) -> "ServiceContext":
        with cls._lock:
            if cls._instance is None:
                cls._instance = ServiceContext(logger)
            return cls._instance

    def syntax_cache_for(self, samdb: Any) -> Any:
        from classes.serialization.syntax_cache import SyntaxCache
        key = id(samdb)
        cache: Any = self.syntax_caches.get(key)
        if cache is None:
            cache = SyntaxCache(samdb)
            self.syntax_caches[key] = cache
        return cache
