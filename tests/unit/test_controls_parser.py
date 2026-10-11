#!/usr/bin/env python3
"""ControlsParser: which client LDAP controls reach the directory."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from classes.parsing.context import RequestContext
from classes.parsing.controls_parser import ControlsParser

GET = "http://schemas.xmlsoap.org/ws/2004/09/transfer/Get"
SHOW_DELETED = "1.2.840.113556.1.4.417"
SHOW_RECYCLED = "1.2.840.113556.1.4.2064"
SHOW_DEACTIVATED_LINK = "1.2.840.113556.1.4.2065"
PAGED_RESULTS = "1.2.840.113556.1.4.319"


# Builds a Get envelope carrying one ad:control element per OID.
def _envelope(*oids: str) -> str:
    controls = "".join(f'<ad:control type="{oid}" criticality="true"/>' for oid in oids)
    return (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing" '
        'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">'
        f'<s:Header><a:Action>{GET}</a:Action><a:MessageID>urn:uuid:c</a:MessageID>'
        '</s:Header>'
        f'<s:Body><ad:controls>{controls}</ad:controls></s:Body></s:Envelope>'
    )


# Get-ADObject -IncludeDeletedObjects sends these three controls.
def test_deleted_object_visibility_controls_translate_to_ldb_names() -> None:
    root = ET.fromstring(_envelope(SHOW_DELETED, SHOW_RECYCLED, SHOW_DEACTIVATED_LINK))
    assert ControlsParser.to_ldb(root) == [
        "show_deleted:1", "show_recycled:1", "show_deactivated_link:1",
    ]


# 2065 used to be translated to "managedBy", which ldb rejects outright.
def test_show_deactivated_link_is_no_longer_an_attribute_name() -> None:
    root = ET.fromstring(_envelope(SHOW_DEACTIVATED_LINK))
    assert ControlsParser.to_ldb(root) == ["show_deactivated_link:1"]


# A single-object Get keeps its SD read and gains only the visibility controls.
def test_object_read_forwards_visibility_controls_only() -> None:
    context = RequestContext.from_xml(_envelope(SHOW_DELETED, PAGED_RESULTS))
    assert ControlsParser.for_object_read(context.ldap_controls) == [
        "sd_flags:1:0", "show_deleted:1",
    ]


# Without client controls the Get behaves exactly as before.
def test_object_read_without_client_controls_is_unchanged() -> None:
    assert ControlsParser.for_object_read(None) == ["sd_flags:1:0"]
