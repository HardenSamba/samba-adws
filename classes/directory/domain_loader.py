from typing import Any, Dict

import ldb

from classes.serialization.ldb_value import LdbValue


class DomainLoader:

    DOMAIN_ATTRS = ["objectGUID", "objectSid", "name", "msDS-Behavior-Version"]

    def __init__(self, samdb: Any) -> None:
        self.samdb: Any = samdb

    def load_domain(self) -> Dict[str, Any]:
        base = self._rootdse("defaultNamingContext")
        if not base:
            return {}
        results = self.samdb.search(
            base=base, scope=ldb.SCOPE_BASE,
            expression="(objectClass=domain)", attrs=self.DOMAIN_ATTRS,
        )
        return self._format(results[0], base) if results else {}

    def _rootdse(self, attr: str) -> str:
        try:
            res = self.samdb.search(base="", scope=ldb.SCOPE_BASE, attrs=[attr])
        except ldb.LdbError:
            return ""
        return LdbValue.text(res[0], attr) if res else ""

    def _format(self, msg: Any, base: str) -> Dict[str, Any]:
        return {
            "dn": str(msg.dn),
            "name": LdbValue.text(msg, "name"),
            "object_guid": LdbValue.guid(msg),
            "sid": LdbValue.sid_b64(msg),
            "domain_mode": LdbValue.text(msg, "msDS-Behavior-Version") or "0",
            "base": base,
            "dns_root": LdbValue.dn_to_dns(base),
            "forest_dns": LdbValue.dn_to_dns(self._rootdse("rootDomainNamingContext")),
            "dns_host": self._rootdse("dnsHostName"),
            "netbios": self._netbios(base),
        }

    def _netbios(self, base: str) -> str:
        cfg = self._rootdse("configurationNamingContext")
        if not cfg:
            return ""
        try:
            res = self.samdb.search(
                base=f"CN=Partitions,{cfg}", scope=ldb.SCOPE_ONELEVEL,
                expression=f"(nCName={base})", attrs=["nETBIOSName"],
            )
        except ldb.LdbError:
            return ""
        return LdbValue.text(res[0], "nETBIOSName") if res else ""
