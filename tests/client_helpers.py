"""Shared WCF response scripts for offline client tests."""

import xml.etree.ElementTree as ET
from typing import Callable

import pytest

import samba_adws.client as client_module
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._request import GET_RESPONSE_ACTION
from src.soap.namespaces import AD, ADDATA, DA, SOAP_ENV, WSA, XSD, XSI
from tests.scripted_transport import ScriptedTransport


# Builds a WCF response correlated to the MessageID in a scripted request.
def response_for(payload: bytes, body: str, relates_to: str = "") -> bytes:
    request = ET.fromstring(decode_xml(payload))
    message_id = request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""
    correlation = relates_to or message_id
    namespaces = (
        f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:ad="{AD}" '
        f'xmlns:addata="{ADDATA}" xmlns:da="{DA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
    )
    xml = (
        f'<s:Envelope {namespaces}><s:Header><a:Action>{GET_RESPONSE_ACTION}</a:Action>'
        f'<a:RelatesTo>{correlation}</a:RelatesTo></s:Header><s:Body>{body}</s:Body>'
        f'</s:Envelope>'
    )
    return encode_xml(xml)


# Replaces the production transport factory with one scripted instance.
def install_transport(
    monkeypatch: pytest.MonkeyPatch, script: Callable[[bytes], bytes]
) -> ScriptedTransport:
    transport = ScriptedTransport(script)

    # Returns the scripted transport for every client session.
    def factory(server: str, port: int, timeout: float) -> ScriptedTransport:
        return transport

    monkeypatch.setattr(client_module, "open_transport", factory)
    return transport


# Returns a malformed SOAP envelope through the real WCF codec.
def malformed_response(_: bytes) -> bytes:
    return encode_xml(f'<s:Envelope xmlns:s="{SOAP_ENV}"/>')


# Simulates a network failure from the scripted exchange.
def failing_response(_: bytes) -> bytes:
    raise OSError("connection refused")
