import uuid
from base64 import b64encode
from typing import Any, List, Optional


class LdbValue:

    @staticmethod
    def text(msg: Any, attr: str) -> str:
        if attr not in msg:
            return ""
        raw = msg[attr][0]
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    @staticmethod
    def guid(msg: Any, attr: str = "objectGUID") -> Optional[str]:
        if attr not in msg:
            return None
        raw = bytes(msg[attr][0])
        return str(uuid.UUID(bytes_le=raw)) if len(raw) == 16 else None

    @staticmethod
    def sid_b64(msg: Any, attr: str = "objectSid") -> Optional[str]:
        if attr not in msg:
            return None
        return b64encode(bytes(msg[attr][0])).decode("ascii")

    @staticmethod
    def dn_to_dns(dn: str) -> str:
        parts = [p.strip()[3:] for p in dn.split(",") if p.strip()[:3].upper() == "DC="]
        return ".".join(parts)

    @staticmethod
    def classes(msg: Any) -> List[str]:
        return [
            c.decode("utf-8") if isinstance(c, bytes) else str(c)
            for c in msg.get("objectClass", [])
        ]
