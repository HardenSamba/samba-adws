"""One directory connection, opened as whoever the request authenticated as."""

import logging
from typing import Any

import ldb
from samba.param import LoadParm
from samba.samdb import SamDB as _SamDB

from classes.faults.exceptions import ADWSAccessDeniedException


# One lazily opened SamDB, bound to the session it was given and no other.
class SambaDB:

    # Holds the session this connection will open as. There is no default.
    def __init__(self, logger: logging.Logger, session_info: Any = None) -> None:
        self.logger = logger
        self._db: Any = None
        self.session_info: Any = session_info

    # Opens on first use, because samba is not thread-safe and the server forks.
    @property
    def db(self) -> Any:
        if self._db is None:
            self._db = self._open()
        return self._db

    # Opens the directory as the session, or refuses to open it at all.
    #
    # This used to read `session_info or system_session()`. A request that
    # reached here with nothing therefore ran as SYSTEM, and every ACL in the
    # domain was evaluated against an identity nobody had authenticated as.
    def _open(self) -> Any:
        if self.session_info is None:
            raise ADWSAccessDeniedException(
                "No authenticated session for this request; refusing to open the directory."
            )
        lp = LoadParm()
        lp.load_default()
        instance = _SamDB(lp=lp, session_info=self.session_info)
        self.logger.info("[DB] SamDB connection established")
        return instance

    # One naming context from the Root DSE, as text.
    def naming_context(self, kind: str = "defaultNamingContext") -> str:
        result = self.db.search(base="", scope=ldb.SCOPE_BASE, attrs=[kind])
        if not result:
            return ""
        raw = result[0].get(kind)
        if not raw:
            return ""
        value = (
            raw[0]
            if hasattr(raw, "__iter__") and not isinstance(raw, str | bytes)
            else raw
        )
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
