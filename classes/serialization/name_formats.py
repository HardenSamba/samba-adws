import logging
from typing import Any, Dict, List, Optional

import ldb
from src.serialization.name_filters import filter_for_offered, first_text
from src.serialization.name_renderers import render_canonical, render_dn, render_guid, render_nt4

SEARCH_ATTRS: List[str] = [
    "distinguishedName", "sAMAccountName", "userPrincipalName",
    "objectGUID", "objectSid", "displayName", "servicePrincipalName",
    "name", "cn",
]


class NameFormatResolver:

    def __init__(self, samdb: Any, logger: logging.Logger) -> None:
        self.samdb: Any = samdb
        self.logger: logging.Logger = logger

    def translate(self, name: str, fmt_offered: str, fmt_desired: str) -> Dict[str, str]:
        if not name:
            return {"name": name, "result": "", "status": "NotFound"}
        try:
            entry = self._lookup(name, fmt_offered)
        except ldb.LdbError:
            return {"name": name, "result": "", "status": "NotFound"}
        if entry is None:
            return {"name": name, "result": "", "status": "NotFound"}
        result = self._render(entry, fmt_desired)
        if not result:
            return {"name": name, "result": "", "status": "NoMapping"}
        return {"name": name, "result": result, "status": "Found"}

    def _lookup(self, name: str, fmt_offered: str) -> Optional[Any]:
        base = self.samdb.naming_context()
        expression = filter_for_offered(name, fmt_offered)
        results = self.samdb.db.search(
            base=base, scope=ldb.SCOPE_SUBTREE,
            expression=expression, attrs=SEARCH_ATTRS,
        )
        return results[0] if results else None

    def _render(self, entry: Any, fmt_desired: str) -> str:
        kind = (fmt_desired or "").lower()
        if "nt4" in kind or "ntaccount" in kind:
            return render_nt4(entry, self.samdb)
        if "userprincipal" in kind or "upn" in kind:
            return first_text(entry, "userPrincipalName")
        if "displayname" in kind:
            return first_text(entry, "displayName") or first_text(entry, "cn")
        if "canonical" in kind:
            return render_canonical(entry, self.samdb)
        if "guid" in kind or "uniqueid" in kind:
            return render_guid(entry, self.samdb)
        if "spn" in kind or "service" in kind:
            return first_text(entry, "servicePrincipalName")
        return render_dn(entry, self.samdb)
