"""Request context extraction from SOAP envelopes."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from classes.parsing.context_enumeration import read_enumerate, read_pull_release
from classes.parsing.context_values import (
    read_core,
    read_requested_attributes,
    unescape_xml_entities,
)
from classes.parsing.xml_chars import restore_tree


# Represents the fields extracted from one ADWS request.
@dataclass
class RequestContext:
    """Structured representation of an ADWS request."""

    action: str
    message_id: str
    object_reference: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    filters: Optional[List[str]] = None
    is_imda: bool = False
    requested_attributes: Optional[List[str]] = None
    base_dn: Optional[str] = None
    ldap_filter: Optional[str] = None
    ldap_scope: Optional[str] = None
    selection_attributes: Optional[List[str]] = None
    enumeration_context: Optional[str] = None
    max_elements: Optional[int] = None
    raw_xml: Optional[str] = None
    ldap_controls: Optional[List[str]] = None

    # Parses an XML envelope and assembles its request context.
    @classmethod
    def from_xml(cls, xml: str) -> "RequestContext":
        """Parse XML to extract request context."""
        try:
            root = restore_tree(ET.fromstring(xml))
            values = read_core(root)
            values["requested_attributes"] = read_requested_attributes(
                root, bool(values["is_imda"])
            )
            values.update(read_enumerate(root))
            values.update(read_pull_release(root))
            values["raw_xml"] = xml
            values["ldap_controls"] = cls._parse_controls(root)
            return cls(**values)
        except Exception as exc:
            raise ValueError(f"Failed to parse request XML: {exc}") from exc

    # Converts supported ADWS controls into their LDB representation.
    @staticmethod
    def _parse_controls(root: ET.Element) -> Optional[List[str]]:
        try:
            from classes.parsing.controls_parser import ControlsParser

            result: Optional[List[str]] = ControlsParser.to_ldb(root) or None
            return result
        except Exception:
            return None

    # Retains the legacy entity-decoding helper for existing callers.
    @staticmethod
    def _unescape_xml_entities(text: str) -> str:
        """Decode the XML entities supported by the legacy parser."""
        return unescape_xml_entities(text)
