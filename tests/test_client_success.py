"""Successful offline contract tests for the public ADWS client."""

import functools
import xml.etree.ElementTree as ET

import pytest

from samba_adws import ADWSClient
from samba_adws._codec import decode_xml
from samba_adws._request import GET_ACTION
from src.soap.namespaces import AD, DA, SOAP_ENV, WSA
from tests.client_helpers import install_transport, response_for

PROJECTED_BODY = (
    '<da:BaseObjectSearchResponse><da:PartialAttribute>'
    '<addata:cn LdapSyntax="UnicodeString"><ad:value xsi:type="xsd:string">Demo</ad:value>'
    '</addata:cn></da:PartialAttribute><da:PartialAttribute><addata:objectGUID '
    'LdapSyntax="OctetString"><ad:value xsi:type="xsd:base64Binary">AQI=</ad:value>'
    '</addata:objectGUID></da:PartialAttribute></da:BaseObjectSearchResponse>'
)
WHOLE_BODY = (
    '<addata:user><addata:cn><ad:value xsi:type="xsd:string">Demo</ad:value></addata:cn>'
    '<addata:memberOf><ad:value xsi:type="xsd:string">CN=One</ad:value>'
    '<ad:value xsi:type="xsd:string">CN=Two</ad:value></addata:memberOf></addata:user>'
)


# Verifies the projected request, correlation, and Python value decoding.
def test_get_by_dn_uses_scripted_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(response_for, body=PROJECTED_BODY)
    transport = install_transport(monkeypatch, script)
    identity = "CN=Démo & Ops,DC=example,DC=test"
    client = ADWSClient("dc.example.test", 9389, 30.0)
    result = client.get_by_dn(identity, ("cn", "objectGUID"))
    client.get_by_dn(identity, ("cn",))
    roots = [ET.fromstring(decode_xml(payload)) for payload in transport.requests]
    ids = [root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") for root in roots]
    header = roots[0].find(f"./{{{SOAP_ENV}}}Header")
    attributes = roots[0].findall(f".//{{{DA}}}AttributeType")
    assert result == {"cn": "Demo", "objectGUID": b"\x01\x02"}
    assert header is not None and header.findtext(f"{{{WSA}}}Action") == GET_ACTION
    assert header.findtext(f"{{{WSA}}}To") == (
        "net.tcp://dc.example.test:9389/ActiveDirectoryWebServices/Windows/Resource"
    )
    assert header.findtext(f"{{{AD}}}objectReferenceProperty") == identity
    assert header.find(f"{{{DA}}}IdentityManagementOperation") is not None
    assert [element.text for element in attributes] == ["addata:cn", "addata:objectGUID"]
    assert ids[0] != ids[1]
    assert transport.closed


# Verifies the default whole-object request and multi-valued tuple result.
def test_get_by_dn_decodes_whole_object(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(response_for, body=WHOLE_BODY)
    transport = install_transport(monkeypatch, script)
    result = ADWSClient("dc.example.test").get_by_dn("CN=Demo,DC=example,DC=test")
    root = ET.fromstring(decode_xml(transport.requests[0]))
    assert root.find(f".//{{{DA}}}BaseObjectSearchRequest") is None
    assert result == {"cn": "Demo", "memberOf": ("CN=One", "CN=Two")}
