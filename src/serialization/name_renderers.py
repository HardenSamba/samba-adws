import uuid
from typing import Any, Optional

import ldb

from src.serialization.name_filters import first_text


def render_dn(entry: Any, _samdb: Any) -> str:
    return str(entry.dn)


def render_nt4(entry: Any, samdb: Any) -> str:
    sam = first_text(entry, "sAMAccountName")
    if not sam:
        return ""
    netbios = _netbios_name(samdb) or ""
    return f"{netbios}\\{sam}" if netbios else sam


def render_canonical(entry: Any, _samdb: Any) -> str:
    dn = str(entry.dn)
    parts = [p.strip() for p in dn.split(",")]
    domain = ".".join(p[3:] for p in parts if p.upper().startswith("DC="))
    rest = [p.split("=", 1)[1] for p in parts if not p.upper().startswith("DC=") and "=" in p]
    if not rest:
        return domain
    return domain + "/" + "/".join(reversed(rest))


def render_guid(entry: Any, _samdb: Any) -> str:
    if "objectGUID" not in entry:
        return ""
    raw = bytes(entry["objectGUID"][0])
    return "{" + str(uuid.UUID(bytes_le=raw)) + "}" if len(raw) == 16 else ""


def _netbios_name(samdb: Any) -> Optional[str]:
    try:
        nc = samdb.naming_context()
        base = f"CN=Partitions,CN=Configuration,{nc}"
        res = samdb.db.search(
            base=base, scope=ldb.SCOPE_SUBTREE,
            expression=f"(nCName={nc})", attrs=["nETBIOSName"],
        )
    except ldb.LdbError:
        return ""
    if not res or "nETBIOSName" not in res[0]:
        return ""
    raw = res[0]["nETBIOSName"][0]
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
