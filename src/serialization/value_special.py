import html
from typing import Tuple, Union

from src.serialization.syntax_constants import XSD_STRING


# Renders an LDAP boolean as the AD wire form TRUE/FALSE, typed xsd:string.
def encode_boolean(value: Union[bytes, object]) -> Tuple[str, str]:
    text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value)
    truthy = text.strip().upper() in ("TRUE", "1", "YES")
    return (XSD_STRING, "TRUE" if truthy else "FALSE")


# Passes the directory-native generalized-time string through as xsd:string.
def encode_generalized_time(value: Union[bytes, object]) -> Tuple[str, str]:
    text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value)
    return (XSD_STRING, html.escape(text.strip(), quote=True))
