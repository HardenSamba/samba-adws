from base64 import b64decode
from typing import Any, Dict, List, Optional

from src.soap.namespaces import DA

NS = {"da": DA}
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


class AttributeParser:

    @classmethod
    def parse_changes(
        cls,
        parent: Any,
        default_op: Optional[str],
        use_change: bool = False,
    ) -> List[Dict[str, Any]]:
        tag = "da:Change" if use_change else "da:AttributeTypeAndValue"
        result: List[Dict[str, Any]] = []
        for node in parent.findall(tag, NS):
            entry = cls._read_entry(node, default_op)
            if entry:
                result.append(entry)
        return result

    @classmethod
    def _read_entry(
        cls,
        node: Any,
        default_op: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        type_elem = node.find("da:AttributeType", NS)
        value_elem = node.find("da:AttributeValue", NS)
        if type_elem is None or type_elem.text is None:
            return None
        op = (node.get("Operation") or default_op or "replace").lower()
        values = cls._read_values(value_elem)
        return {"name": cls._strip_prefix(type_elem.text), "operation": op, "values": values}

    @staticmethod
    def _read_values(value_elem: Any) -> List[Any]:
        if value_elem is None:
            return []
        out: List[Any] = []
        for child in list(value_elem):
            if child.text is None:
                continue
            xtype = child.get(XSI_TYPE) or ""
            if xtype.endswith("base64Binary"):
                try:
                    out.append(b64decode(child.text))
                except Exception:
                    out.append(child.text)
            else:
                out.append(child.text)
        if not out and value_elem.text and value_elem.text.strip():
            out.append(value_elem.text.strip())
        return out

    @staticmethod
    def _strip_prefix(text: str) -> str:
        cleaned = text.strip()
        for prefix in ("addata:", "ad:"):
            if cleaned.startswith(prefix):
                return cleaned[len(prefix):]
        return cleaned
