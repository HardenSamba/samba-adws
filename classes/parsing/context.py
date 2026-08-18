"""
Request context extraction - parses SOAP request into structured context
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RequestContext:
    """Structured representation of an ADWS request"""
    action: str
    message_id: str
    object_reference: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    filters: Optional[List[str]] = None
    is_imda: bool = False
    requested_attributes: Optional[List[str]] = None

    # Enumerate/LdapQuery fields
    base_dn: Optional[str] = None  # Base DN for LDAP search (from <adlq:BaseObject>)
    ldap_filter: Optional[str] = None  # LDAP filter (from <adlq:Filter>)
    ldap_scope: Optional[str] = None  # LDAP scope: "Base", "OneLevel", or "Subtree"
    selection_attributes: Optional[List[str]] = None  # Attributes from <ad:SelectionProperty>

    # Pull/Release fields
    enumeration_context: Optional[str] = None  # UUID context from <wsen:EnumerationContext>
    max_elements: Optional[int] = None  # Max elements to return from <wsen:MaxElements>

    # Raw request XML (used by CRUD/CustomAction handlers to re-parse body)
    raw_xml: Optional[str] = None

    # LDAP controls parsed from <ad:controls>
    ldap_controls: Optional[List[str]] = None

    @classmethod
    def from_xml(cls, xml: str) -> 'RequestContext':
        """Parse XML to extract request context"""
        try:
            root = ET.fromstring(xml)

            # Define namespaces - use the correct WS-Addressing namespace
            ns = {
                'soap': 'http://www.w3.org/2003/05/soap-envelope',  # SOAP 1.2
                'soap11': 'http://schemas.xmlsoap.org/soap/envelope/',  # SOAP 1.1 fallback
                'a': 'http://www.w3.org/2005/08/addressing',  # WS-Addressing 2005/08
                'ad': 'http://schemas.microsoft.com/2008/1/ActiveDirectory',
                'da': 'http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess',
                'wsen': 'http://schemas.xmlsoap.org/ws/2004/09/enumeration',  # WS-Enumeration
                'adlq': 'http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery'
            }

            # Extract key fields - try both SOAP 1.2 and 1.1 namespaces
            action = root.findtext('.//a:Action', namespaces=ns)
            if not action:
                # Try without namespace
                action = root.findtext('.//Action')

            message_id = root.findtext('.//a:MessageID', namespaces=ns)
            if not message_id:
                message_id = root.findtext('.//MessageID')

            object_ref = root.findtext('.//ad:objectReferenceProperty', namespaces=ns)

            is_imda = (
                root.find('.//da:IdentityManagementOperation', namespaces=ns) is not None or
                root.find('.//da:BaseObjectSearchRequest', namespaces=ns) is not None
            )

            # Extract requested attributes (IMDA format)
            requested_attributes = []
            if is_imda:
                attr_types = root.findall('.//da:AttributeType', namespaces=ns)
                for attr_elem in attr_types:
                    attr_text = attr_elem.text
                    if attr_text:
                        # Strip 'addata:' prefix if present
                        if attr_text.startswith('addata:'):
                            attr_name = attr_text[7:]  # Remove 'addata:' prefix
                        else:
                            attr_name = attr_text
                        requested_attributes.append(attr_name)

            # Parse Enumerate/LdapQuery request
            base_dn = None
            ldap_filter = None
            ldap_scope = None
            selection_attributes = None

            # Check for Enumerate element
            enumerate_elem = root.find('.//wsen:Enumerate', namespaces=ns)
            if enumerate_elem is not None:
                # Extract LdapQuery parameters
                base_dn_elem = enumerate_elem.find('.//adlq:BaseObject', namespaces=ns)
                if base_dn_elem is not None and base_dn_elem.text:
                    base_dn = base_dn_elem.text

                filter_elem = enumerate_elem.find('.//adlq:Filter', namespaces=ns)
                if filter_elem is not None and filter_elem.text:
                    # Decode XML entities (e.g., &amp; → &)
                    ldap_filter = cls._unescape_xml_entities(filter_elem.text)

                scope_elem = enumerate_elem.find('.//adlq:Scope', namespaces=ns)
                if scope_elem is not None and scope_elem.text:
                    ldap_scope = scope_elem.text  # "Base", "OneLevel", or "Subtree"

                # Extract SelectionProperty attributes
                selection_attrs = []
                selection_props = enumerate_elem.findall('.//ad:SelectionProperty', namespaces=ns)
                for prop_elem in selection_props:
                    if prop_elem.text:
                        # Strip prefixes (ad:, addata:)
                        attr_name = prop_elem.text
                        if attr_name.startswith('ad:'):
                            attr_name = attr_name[3:]
                        elif attr_name.startswith('addata:'):
                            attr_name = attr_name[7:]
                        selection_attrs.append(attr_name)

                if selection_attrs:
                    selection_attributes = selection_attrs

            # Parse Pull/Release request
            enumeration_context = None
            max_elements = None

            # Check for Pull element
            pull_elem = root.find('.//wsen:Pull', namespaces=ns)
            if pull_elem is not None:
                # Extract EnumerationContext (UUID)
                ctx_elem = pull_elem.find('.//wsen:EnumerationContext', namespaces=ns)
                if ctx_elem is not None and ctx_elem.text:
                    enumeration_context = ctx_elem.text

                # Extract MaxElements
                max_elem = pull_elem.find('.//wsen:MaxElements', namespaces=ns)
                if max_elem is not None and max_elem.text:
                    try:
                        max_elements = int(max_elem.text)
                    except ValueError:
                        max_elements = None

            # Check for Release element
            release_elem = root.find('.//wsen:Release', namespaces=ns)
            if release_elem is not None:
                # Extract EnumerationContext (UUID) for Release
                ctx_elem = release_elem.find('.//wsen:EnumerationContext', namespaces=ns)
                if ctx_elem is not None and ctx_elem.text:
                    enumeration_context = ctx_elem.text

            return cls(
                action=action or "Unknown",
                message_id=message_id or "",
                object_reference=object_ref,
                is_imda=is_imda,
                requested_attributes=requested_attributes if requested_attributes else None,
                base_dn=base_dn,
                ldap_filter=ldap_filter,
                ldap_scope=ldap_scope,
                selection_attributes=selection_attributes,
                enumeration_context=enumeration_context,
                max_elements=max_elements,
                raw_xml=xml,
                ldap_controls=cls._parse_controls(root),
            )

        except Exception as e:
            raise ValueError(f"Failed to parse request XML: {str(e)}") from e

    @staticmethod
    def _parse_controls(root: ET.Element) -> Optional[List[str]]:
        try:
            from classes.parsing.controls_parser import ControlsParser
            result: Optional[List[str]] = ControlsParser.to_ldb(root) or None
            return result
        except Exception:
            return None

    @staticmethod
    def _unescape_xml_entities(text: str) -> str:
        """Decode XML entities like &amp; to &"""
        if not text:
            return text
        return (text
                .replace('&amp;', '&')
                .replace('&lt;', '<')
                .replace('&gt;', '>')
                .replace('&quot;', '"')
                .replace('&apos;', "'"))
