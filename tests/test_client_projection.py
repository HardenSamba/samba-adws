"""Client-to-server IMDA projection tests."""

import xml.etree.ElementTree as ET

from classes.parsing.context import RequestContext
from samba_adws._request import build_get_request
from src.soap.namespaces import DA

SYNTHETIC_PROPERTIES = (
    "DistinguishedName",
    "RelativeDistinguishedName",
    "ObjectReferenceProperty",
    "container-hierarchy-parent",
)


# Synthetic properties use their canonical AD QName while data stays in addata.
def test_synthetic_properties_are_emitted_with_canonical_case() -> None:
    xml, _ = build_get_request(
        "dc.example.test", 9389, "CN=Demo,DC=example,DC=test",
        SYNTHETIC_PROPERTIES + ("displayName",),
    )
    root = ET.fromstring(xml)
    names = [element.text for element in root.findall(f".//{{{DA}}}AttributeType")]
    assert names == [
        "ad:distinguishedName",
        "ad:relativeDistinguishedName",
        "ad:objectReferenceProperty",
        "ad:container-hierarchy-parent",
        "addata:displayName",
    ]


# The server removes both supported QName prefixes before querying LDB.
def test_get_context_strips_ad_and_addata_prefixes() -> None:
    xml, _ = build_get_request(
        "dc.example.test", 9389, "CN=Demo,DC=example,DC=test",
        SYNTHETIC_PROPERTIES + ("displayName",),
    )
    context = RequestContext.from_xml(xml)
    assert context.requested_attributes == [
        "distinguishedName",
        "relativeDistinguishedName",
        "objectReferenceProperty",
        "container-hierarchy-parent",
        "displayName",
    ]
