"""Core SOAP values used to build a request context."""

import xml.etree.ElementTree as ET
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional

from src.soap.namespaces import AD, ADLQ, DA, SOAP_ENV, WSA, WSEN

NAMESPACES: Mapping[str, str] = MappingProxyType({
    "soap": SOAP_ENV,
    "soap11": "http://schemas.xmlsoap.org/soap/envelope/",
    "a": WSA,
    "ad": AD,
    "da": DA,
    "wsen": WSEN,
    "adlq": ADLQ,
})


# Returns a mutable namespace copy for ElementTree's narrow type contract.
def xml_namespaces() -> Dict[str, str]:
    return dict(NAMESPACES)


# Removes the QName prefixes used for ADWS attribute selections.
def strip_attribute_prefix(name: str) -> str:
    for prefix in ("addata:", "ad:"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# Decodes the XML entities handled by the original request parser.
def unescape_xml_entities(text: str) -> str:
    if not text:
        return text
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


# Reads addressing, object-reference, and IMDA marker values.
def read_core(root: ET.Element) -> Dict[str, Any]:
    namespaces = xml_namespaces()
    action = root.findtext(".//a:Action", namespaces=namespaces)
    if not action:
        action = root.findtext(".//Action")
    message_id = root.findtext(".//a:MessageID", namespaces=namespaces)
    if not message_id:
        message_id = root.findtext(".//MessageID")
    is_imda = (
        root.find(".//da:IdentityManagementOperation", namespaces) is not None
        or root.find(".//da:BaseObjectSearchRequest", namespaces) is not None
    )
    return {
        "action": action or "Unknown",
        "message_id": message_id or "",
        "object_reference": root.findtext(
            ".//ad:objectReferenceProperty", namespaces=namespaces
        ),
        "is_imda": is_imda,
    }


# Reads and normalizes IMDA AttributeType values.
def read_requested_attributes(
    root: ET.Element, is_imda: bool
) -> Optional[List[str]]:
    if not is_imda:
        return None
    elements = root.findall(".//da:AttributeType", xml_namespaces())
    texts = (element.text for element in elements)
    attributes = [strip_attribute_prefix(text) for text in texts if text]
    return attributes or None
