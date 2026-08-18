from base64 import b64decode
from typing import Any, Dict, List, Optional

from src.soap.namespaces import AD, DA

NS = {"ad": AD, "da": DA}

LDB_CONTROL_BY_OID = {
    "1.2.840.113556.1.4.319": "paged_results",
    "1.2.840.113556.1.4.473": "server_sort",
    "1.2.840.113556.1.4.474": "sort_resp",
    "1.2.840.113556.1.4.529": "extended_dn",
    "1.2.840.113556.1.4.801": "sd_flags",
    "1.2.840.113556.1.4.805": "tree_delete",
    "1.2.840.113556.1.4.521": "crossdom_move_target",
    "1.2.840.113556.1.4.417": "show_deleted",
    "1.2.840.113556.1.4.1340": "show_recycled",
    "1.2.840.113556.1.4.2026": "show_deactivated_link",
    "1.2.840.113556.1.4.1413": "permissive_modify",
    "1.2.840.113556.1.4.1339": "domain_scope",
    "1.2.840.113556.1.4.2065": "managedBy",
    "1.2.840.113556.1.4.1504": "asq",
    "1.2.840.113556.1.4.1948": "search_notification",
    "1.2.840.113556.1.4.2064": "show_recycled",
    "2.16.840.1.113730.3.4.2": "manageDSAIT",
    "1.2.840.113556.1.4.1338": "verify_name",
    "1.2.840.113556.1.4.841": "dirsync",
}


class ControlsParser:

    @classmethod
    def parse(cls, root: Any) -> List[Dict[str, Any]]:
        controls: List[Dict[str, Any]] = []
        for elem in root.findall(".//ad:controls/ad:control", NS):
            entry = cls._read_one(elem)
            if entry:
                controls.append(entry)
        return controls

    @classmethod
    def to_ldb(cls, root: Any) -> List[str]:
        out: List[str] = []
        for ctrl in cls.parse(root):
            translated = cls._translate(ctrl)
            if translated:
                out.append(translated)
        return out

    @staticmethod
    def _read_one(elem: Any) -> Optional[Dict[str, Any]]:
        oid = elem.get("type") or elem.get("OID")
        if not oid:
            return None
        critical = (elem.get("criticality") or "false").lower() == "true"
        value_elem = elem.find("ad:controlValue", NS)
        raw = value_elem.text if value_elem is not None else None
        return {"oid": oid.strip(), "critical": critical, "value": raw}

    @staticmethod
    def _translate(ctrl: Dict[str, Any]) -> Optional[str]:
        name = LDB_CONTROL_BY_OID.get(ctrl["oid"])
        if not name:
            return None
        criticality = "1" if ctrl["critical"] else "0"
        if not ctrl["value"]:
            return f"{name}:{criticality}"
        try:
            decoded = b64decode(ctrl["value"]).decode("utf-8", errors="ignore")
            decoded = decoded.replace(":", "").strip()
        except Exception:
            decoded = ""
        return f"{name}:{criticality}:{decoded}" if decoded else f"{name}:{criticality}"
