from typing import Any, Dict, List, Optional

import ldb


# Builds LDB message attributes from decoded ADWS values.
class LdapAttrBuilder:

    # Encodes one decoded value according to its LDAP attribute syntax.
    @staticmethod
    def encode_value(attr_name: str, raw_text: Any) -> bytes:
        if raw_text is None:
            return b""
        if isinstance(raw_text, bytes):
            return raw_text
        if not isinstance(raw_text, str):
            raise TypeError("LDAP attribute values must be text or bytes")
        if attr_name.lower() in ("unicodepwd",):
            return ('"' + raw_text + '"').encode("utf-16-le")
        return raw_text.encode("utf-8")

    # Builds a complete LDB modification message from parsed entries.
    @classmethod
    def build_message(
        cls,
        samdb: Any,
        dn: str,
        entries: List[Dict[str, Any]],
        default_flag: int = ldb.FLAG_MOD_REPLACE,
    ) -> Any:
        msg = ldb.Message(ldb.Dn(samdb, dn))
        for entry in entries:
            cls._apply_entry(msg, entry, default_flag)
        return msg

    # Applies one parsed modification entry to an LDB message.
    @classmethod
    def _apply_entry(cls, msg: Any, entry: Dict[str, Any], default_flag: int) -> None:
        name = entry["name"]
        op = entry.get("operation", "replace")
        flag = cls._flag_for(op, default_flag)
        encoded = [cls.encode_value(name, v) for v in entry.get("values", [])]
        msg[name] = ldb.MessageElement(encoded, flag, name)

    # Maps an ADWS operation name to its LDB modification flag.
    @staticmethod
    def _flag_for(operation: Optional[str], default_flag: int) -> int:
        op = (operation or "").lower()
        if op == "add":
            return int(ldb.FLAG_MOD_ADD)
        if op in ("delete", "remove"):
            return int(ldb.FLAG_MOD_DELETE)
        if op == "replace":
            return int(ldb.FLAG_MOD_REPLACE)
        return default_flag
