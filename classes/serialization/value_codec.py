import html
import re
from base64 import b64encode
from typing import Any, Tuple

from src.serialization.syntax_constants import (
    SYNTAX_BOOLEAN,
    SYNTAX_GENERALIZED_TIME,
    SYNTAX_GUID,
    SYNTAX_INTEGER,
    SYNTAX_LARGE_INTEGER,
    SYNTAX_OCTET_STRING,
    SYNTAX_SID,
    XSD_BASE64,
    XSD_STRING,
)
from src.serialization.value_special import encode_boolean, encode_generalized_time

# XML 1.0 forbids these control chars; bytes that decode as UTF-8 but contain
# them (e.g. unmapped binary attrs like tokenGroups SIDs) must go to base64.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# Encodes an LDAP attribute value into its (xsi:type, wire text) pair.
class ValueCodec:

    # Stores the syntax registry used to pick each value's encoding.
    def __init__(self, syntaxes: Any) -> None:
        self.syntaxes = syntaxes

    # Maps a value to (xsi:type, encoded text) according to its LDAP syntax.
    def encode_to_xsd(self, attr_name: str, raw_value: Any) -> Tuple[str, str]:
        value = raw_value
        if value is not None and value.__class__.__name__ == "MessageElement":
            value = bytes(value[0]) if len(value) > 0 else None
        if value is None:
            return (XSD_STRING, "")
        oid = self.syntaxes.syntax_for(attr_name)
        if oid == SYNTAX_BOOLEAN:
            return encode_boolean(value)
        if oid == SYNTAX_GENERALIZED_TIME:
            return encode_generalized_time(value)
        if oid in (SYNTAX_INTEGER, SYNTAX_LARGE_INTEGER):
            return self._encode_integer(value)
        if oid in (SYNTAX_OCTET_STRING, SYNTAX_SID, SYNTAX_GUID):
            return self._encode_binary(value)
        return self._encode_string(value)

    # Encodes Integer/LargeInteger as decimal text typed xsd:string.
    def _encode_integer(self, value: Any) -> Tuple[str, str]:
        if isinstance(value, bytes):
            try:
                return (XSD_STRING, value.decode("ascii"))
            except UnicodeDecodeError:
                return (XSD_STRING, "0")
        return (XSD_STRING, str(value))

    # Encodes byte values as base64Binary (octet/SID/GUID/NTSD syntaxes).
    def _encode_binary(self, value: Any) -> Tuple[str, str]:
        if isinstance(value, bytes):
            return (XSD_BASE64, b64encode(value).decode("ascii"))
        return (XSD_STRING, html.escape(str(value), quote=True))

    # Encodes text as xsd:string, falling back to base64 for non-UTF-8/control bytes.
    def _encode_string(self, value: Any) -> Tuple[str, str]:
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                return (XSD_BASE64, b64encode(value).decode("ascii"))
            if _CTRL.search(text):
                return (XSD_BASE64, b64encode(value).decode("ascii"))
            return (XSD_STRING, html.escape(text, quote=True))
        return (XSD_STRING, html.escape(str(value), quote=True))
