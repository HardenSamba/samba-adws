"""Conversion of ADWS Get response attributes into Python values."""

import base64
import binascii
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Tuple

from samba_adws.errors import ADWSClientError
from src.soap.namespaces import AD, XSI


# Converts every AD attribute in a SOAP body into a mapping entry.
def decode_body(body: ET.Element) -> Dict[str, object]:
    result = decode_object(body)
    if not result:
        raise ADWSClientError("Get response contains no attributes", "MalformedResponse")
    return result


# Converts one element's AD attributes into a mapping, empty if it has none.
#
# Separate from `decode_body` because a Pull answers with many objects and an
# object with no attributes is a fact about that object rather than a malformed
# response - a caller that projected attributes an object does not carry gets
# an empty entry, not an exception that loses the whole page.
def decode_object(element: ET.Element) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for attribute in _attribute_elements(element):
        name, value = _decode_attribute(attribute)
        result[name] = value
    return result


# Finds elements whose direct children are AD value elements.
def _attribute_elements(body: ET.Element) -> Iterable[ET.Element]:
    value_tag = f"{{{AD}}}value"
    return (
        element for element in body.iter()
        if any(child.tag == value_tag for child in element)
    )


# Returns one local attribute name and its scalar or tuple value.
def _decode_attribute(element: ET.Element) -> Tuple[str, object]:
    name = element.tag.rsplit("}", 1)[-1]
    values = [_decode_value(child) for child in element if child.tag == f"{{{AD}}}value"]
    if len(values) == 1:
        return name, values[0]
    return name, tuple(values)


# Converts one AD value according to the WCF-preserved xsi:type QName.
def _decode_value(element: ET.Element) -> object:
    text = element.text or ""
    value_type = element.attrib.get(f"{{{XSI}}}type", "xsd:string")
    if not value_type.endswith(":base64Binary") and value_type != "base64Binary":
        return text
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ADWSClientError("Invalid base64 attribute value", "MalformedResponse") from error
