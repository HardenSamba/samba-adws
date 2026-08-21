import logging
from typing import Any, List, Optional

import ldb
from samba.param import LoadParm
from samba.samdb import SamDB as _SamDB

from classes.faults.exceptions import ADWSAuthenticationException


# Per-process directory handle scoped to one caller's authenticated session.
class SambaDB:

    # Holds the caller's session; the directory is not opened until first use,
    # so a fault-only path that never touches the directory need not carry one.
    def __init__(self, logger: logging.Logger, session_info: Any = None) -> None:
        self.logger = logger
        self._db: Any = None
        self.session_info: Any = session_info

    # Lazily opens the SamDB on first use, once per forked worker process.
    @property
    def db(self) -> Any:
        if self._db is None:
            self._db = self._open()
        return self._db

    # Opens the SamDB under the caller's session so Samba enforces that
    # principal's rights; refuses to fall back to SYSTEM (samba-adws#8).
    def _open(self) -> Any:
        if self.session_info is None:
            raise ADWSAuthenticationException(
                "SambaDB has no authenticated session; a request path must not "
                "open the directory as SYSTEM (samba-adws#8). A local maintenance "
                "caller must pass system_session() explicitly.")
        lp = LoadParm()
        lp.load_default()
        instance = _SamDB(lp=lp, session_info=self.session_info)
        self.logger.info("[DB] SamDB connection established")
        return instance

    # Runs an LDB search on the caller's directory handle.
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

    # Reads a naming-context DN from the RootDSE (defaultNamingContext, etc.).
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
