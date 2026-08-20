"""WS-Enumeration values used to build a request context."""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from classes.parsing.context_values import (
    strip_attribute_prefix,
    unescape_xml_entities,
    xml_namespaces,
)


# Returns meaningful element text for a relative namespace-aware path.
def _element_text(element: ET.Element, path: str) -> Optional[str]:
    found = element.find(path, xml_namespaces())
    return found.text if found is not None and found.text else None


# Reads normalized SelectionProperty values from an Enumerate element.
def _selection_attributes(element: ET.Element) -> Optional[List[str]]:
    texts = (
        prop.text
        for prop in element.findall(".//ad:SelectionProperty", xml_namespaces())
    )
    attributes = [strip_attribute_prefix(text) for text in texts if text]
    return attributes or None


# Reads LDAP query values from an optional Enumerate element.
def read_enumerate(root: ET.Element) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "base_dn": None,
        "ldap_filter": None,
        "ldap_scope": None,
        "selection_attributes": None,
    }
    enumerate_element = root.find(".//wsen:Enumerate", xml_namespaces())
    if enumerate_element is None:
        return values
    raw_filter = _element_text(enumerate_element, ".//adlq:Filter")
    values["base_dn"] = _element_text(enumerate_element, ".//adlq:BaseObject")
    values["ldap_filter"] = unescape_xml_entities(raw_filter) if raw_filter else None
    values["ldap_scope"] = _element_text(enumerate_element, ".//adlq:Scope")
    values["selection_attributes"] = _selection_attributes(enumerate_element)
    return values


# Converts a non-empty MaxElements value, ignoring invalid integers.
def _max_elements(element: ET.Element) -> Optional[int]:
    raw_value = _element_text(element, ".//wsen:MaxElements")
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


# Reads Pull values and lets a populated Release context override them.
def read_pull_release(root: ET.Element) -> Dict[str, Any]:
    context = None
    maximum = None
    pull = root.find(".//wsen:Pull", xml_namespaces())
    if pull is not None:
        context = _element_text(pull, ".//wsen:EnumerationContext")
        maximum = _max_elements(pull)
    release = root.find(".//wsen:Release", xml_namespaces())
    if release is not None:
        release_context = _element_text(release, ".//wsen:EnumerationContext")
        if release_context:
            context = release_context
    return {"enumeration_context": context, "max_elements": maximum}
