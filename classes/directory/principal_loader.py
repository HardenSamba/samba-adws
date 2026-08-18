from typing import Any, Dict, List, Optional, Tuple

import ldb

from classes.serialization.ldb_value import LdbValue


class PrincipalLoader:

    PRINCIPAL_ATTRS = [
        "objectGUID", "objectSid", "sAMAccountName", "distinguishedName",
        "objectClass", "name", "groupType",
    ]

    def __init__(self, samdb: Any) -> None:
        self.samdb: Any = samdb

    def load_by_dn(self, dn: str) -> Optional[Dict[str, Any]]:
        try:
            results = self.samdb.search(
                base=dn, scope=ldb.SCOPE_BASE,
                expression="(objectClass=*)", attrs=self.PRINCIPAL_ATTRS,
            )
        except ldb.LdbError:
            return None
        return self._to_principal(results[0]) if results else None

    def load_many(self, dns: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for dn in dns:
            entry = self.load_by_dn(dn)
            if entry:
                out.append(entry)
        return out

    @staticmethod
    def _to_principal(msg: Any) -> Dict[str, Any]:
        classes = LdbValue.classes(msg)
        dn = str(msg.dn) if msg.dn else ""
        scope, gtype = PrincipalLoader._group_flags(LdbValue.text(msg, "groupType"))
        return {
            "name": LdbValue.text(msg, "name"),
            "object_guid": LdbValue.guid(msg),
            "sid": LdbValue.sid_b64(msg),
            "dn": dn,
            "object_class": classes[-1] if classes else "top",
            "object_types": classes or ["top"],
            "sam": LdbValue.text(msg, "sAMAccountName"),
            "server": LdbValue.dn_to_dns(dn),
            "group_scope": scope,
            "group_type": gtype,
        }

    @staticmethod
    def _group_flags(raw: str) -> Tuple[str, str]:
        if not raw:
            return "Global", "Security"
        value = int(raw) & 0xFFFFFFFF
        scope = "DomainLocal" if value & 0x4 else "Universal" if value & 0x8 else "Global"
        gtype = "Security" if value & 0x80000000 else "Distribution"
        return scope, gtype
