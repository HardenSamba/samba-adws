import logging
from typing import Any, List, Optional

import ldb
from samba.auth import system_session
from samba.param import LoadParm
from samba.samdb import SamDB as _SamDB


class SambaDB:

    def __init__(self, logger: logging.Logger, session_info: Any = None) -> None:
        self.logger = logger
        self._db: Any = None
        self.session_info: Any = session_info or system_session()

    @property
    def db(self) -> Any:
        if self._db is None:
            self._db = self._open()
        return self._db

    def _open(self) -> Any:
        lp = LoadParm()
        lp.load_default()
        instance = _SamDB(lp=lp, session_info=self.session_info)
        self.logger.info("[DB] SamDB connection established")
        return instance

    def search(
        self,
        base: str,
        scope: Any,
        expression: str,
        attrs: Optional[List[str]] = None,
        controls: Optional[Any] = None,
    ) -> Any:
        return self.db.search(
            base=base, scope=scope, expression=expression,
            attrs=attrs, controls=controls,
        )

    def naming_context(self, kind: str = "defaultNamingContext") -> str:
        result = self.db.search(base="", scope=ldb.SCOPE_BASE, attrs=[kind])
        if not result:
            return ""
        raw = result[0].get(kind)
        if not raw:
            return ""
        value = (
            raw[0]
            if hasattr(raw, "__iter__") and not isinstance(raw, (str, bytes))
            else raw
        )
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
