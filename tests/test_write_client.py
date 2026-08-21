"""Offline contract tests for the read-write ADWS client surface."""

import functools
import xml.etree.ElementTree as ET

import pytest

from samba_adws import ADWSClientError, ADWSWriteClient
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._write_request import (
    CREATE_ACTION, DELETE_ACTION, PUT_ACTION, SET_PASSWORD_ACTION,
)
from src.soap.namespaces import AD, CUSTOM_ACTIONS, DA, SOAP_ENV, WSA, WST
from tests.client_helpers import install_transport

FACTORY = "net.tcp://dc.example.test:9389/ActiveDirectoryWebServices/Windows/ResourceFactory"
RESOURCE = "net.tcp://dc.example.test:9389/ActiveDirectoryWebServices/Windows/Resource"


# Builds a correlated write response carrying the given reply action and body.
def write_response(payload: bytes, action: str, body: str = "") -> bytes:
    request = ET.fromstring(decode_xml(payload))
    message_id = request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""
    xml = (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:Action>{action}</a:Action><a:RelatesTo>{message_id}</a:RelatesTo>'
        f'</s:Header><s:Body>{body}</s:Body></s:Envelope>'
    )
    return encode_xml(xml)


# Builds a correlated SOAP 1.2 fault response for the scripted request.
def fault_response(payload: bytes, reason: str = "directory refused the write") -> bytes:
    request = ET.fromstring(decode_xml(payload))
    message_id = request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""
    xml = (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:RelatesTo>{message_id}</a:RelatesTo></s:Header><s:Body><s:Fault>'
        f'<s:Code><s:Value>s:Receiver</s:Value></s:Code>'
        f'<s:Reason><s:Text>{reason}</s:Text></s:Reason></s:Fault></s:Body></s:Envelope>'
    )
    return encode_xml(xml)


# Returns the parsed request the client sent to the scripted transport.
def sent_request(transport: object, index: int = 0) -> ET.Element:
    return ET.fromstring(decode_xml(transport.requests[index]))  # type: ignore[attr-defined]


# Create issues a Create to the ResourceFactory with the RDN and parent split out.
def test_create_builds_factory_add_request(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(write_response, action=f"{WST}/CreateResponse")
    transport = install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    client.create("CN=Ann,CN=Users,DC=example,DC=test",
                  {"objectClass": ["user"], "sAMAccountName": ["ann"]})
    root = sent_request(transport)
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    types = [e.text for e in root.findall(f".//{{{DA}}}AttributeType")]
    assert header is not None
    assert header.findtext(f"{{{WSA}}}Action") == CREATE_ACTION
    assert header.findtext(f"{{{WSA}}}To") == FACTORY
    assert header.find(f"{{{DA}}}IdentityManagementOperation") is not None
    assert "ad:relativeDistinguishedName" in types
    assert "ad:container-hierarchy-parent" in types
    assert "addata:sAMAccountName" in types
    assert root.find(f".//{{{DA}}}AddRequest") is not None


# Modify issues a Put whose Changes replace the named attributes.
def test_modify_builds_put_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(write_response, action=f"{WST}/PutResponse")
    transport = install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    client.modify("CN=Ann,CN=Users,DC=example,DC=test", {"description": ["x & y"]})
    root = sent_request(transport)
    change = root.find(f".//{{{DA}}}ModifyRequest/{{{DA}}}Change")
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    assert header is not None and header.findtext(f"{{{WSA}}}Action") == PUT_ACTION
    assert header.findtext(f"{{{WSA}}}To") == RESOURCE
    assert change is not None and change.get("Operation") == "replace"
    assert change.findtext(f"{{{DA}}}AttributeType") == "addata:description"


# Delete issues an empty-bodied Delete against the target DN.
def test_delete_builds_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(write_response, action=f"{WST}/DeleteResponse")
    transport = install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    client.delete("CN=Ann,CN=Users,DC=example,DC=test")
    root = sent_request(transport)
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    assert header is not None and header.findtext(f"{{{WSA}}}Action") == DELETE_ACTION
    assert header.findtext(f"{{{AD}}}objectReferenceProperty") == \
        "CN=Ann,CN=Users,DC=example,DC=test"
    assert root.find(f".//{{{DA}}}AddRequest") is None


# Rename issues a Put carrying the new RDN and parent as modrdn Changes.
def test_rename_builds_modrdn(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(write_response, action=f"{WST}/PutResponse")
    transport = install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    client.rename("CN=Ann,CN=Users,DC=example,DC=test",
                  "CN=Anne,CN=People,DC=example,DC=test")
    root = sent_request(transport)
    types = [e.text for e in root.findall(f".//{{{DA}}}AttributeType")]
    values = [e.text for e in root.findall(f".//{{{AD}}}value")]
    assert "ad:relativeDistinguishedName" in types
    assert "CN=Anne" in values and "CN=People,DC=example,DC=test" in values


# SetPassword carries the secret in the sealed body, never in a header.
def test_set_password_carries_secret_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = f'<SetPasswordResponse xmlns="{CUSTOM_ACTIONS}"></SetPasswordResponse>'
    script = functools.partial(
        write_response, action=f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse",
        body=body)
    transport = install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    client.set_password("CN=Ann,CN=Users,DC=example,DC=test", "S3cr3t!<>")
    root = sent_request(transport)
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    assert header is not None and header.findtext(f"{{{WSA}}}Action") == SET_PASSWORD_ACTION
    assert root.findtext(f".//{{{CUSTOM_ACTIONS}}}NewPassword") == "S3cr3t!<>"
    assert "S3cr3t" not in ET.tostring(header, encoding="unicode")


# A SOAP fault on any write crosses the boundary as a typed client error.
def test_write_fault_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    install_transport(monkeypatch, fault_response)
    client = ADWSWriteClient("dc.example.test")
    with pytest.raises(ADWSClientError) as caught:
        client.delete("CN=Ghost,CN=Users,DC=example,DC=test")
    assert caught.value.target == "CN=Ghost,CN=Users,DC=example,DC=test"


# A response correlated to the wrong request is rejected, not trusted.
def test_correlation_mismatch_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(_mismatched, action=f"{WST}/PutResponse")
    install_transport(monkeypatch, script)
    client = ADWSWriteClient("dc.example.test")
    with pytest.raises(ADWSClientError) as caught:
        client.modify("CN=Ann,CN=Users,DC=example,DC=test", {"description": ["y"]})
    assert caught.value.code == "CorrelationError"


# Builds a write response whose RelatesTo deliberately does not match.
def _mismatched(payload: bytes, action: str) -> bytes:
    xml = (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:Action>{action}</a:Action><a:RelatesTo>urn:uuid:nope</a:RelatesTo>'
        f'</s:Header><s:Body></s:Body></s:Envelope>'
    )
    return encode_xml(xml)


# Bad inputs are rejected before any network exchange occurs.
def test_validation_rejects_bad_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(
        monkeypatch, functools.partial(write_response, action=f"{WST}/PutResponse"))
    client = ADWSWriteClient("dc.example.test")
    dn = "CN=Ann,CN=Users,DC=example,DC=test"
    with pytest.raises(ADWSClientError):
        client.create(dn, {"cn": "not-a-sequence"})  # type: ignore[dict-item]
    with pytest.raises(ADWSClientError):
        client.rename(dn, "   ")
    with pytest.raises(ADWSClientError):
        client.set_password(dn, "")
    assert transport.requests == []
