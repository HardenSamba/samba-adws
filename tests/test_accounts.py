"""The order the three account exchanges go in, read back off the wire."""

import xml.etree.ElementTree as ET
from typing import List

import pytest

from samba_adws import ADWSClientError, ADWSWriteClient
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._write_request import (
    CREATE_ACTION, PUT_ACTION, SET_PASSWORD_ACTION,
)
from samba_adws.accounts import ENABLED, NewUser, create_user
from src.soap.namespaces import AD, CUSTOM_ACTIONS, DA, SOAP_ENV, WSA, WST
from tests.client_helpers import install_transport

ANN = "CN=Ann,CN=Users,DC=example,DC=test"
ATTRIBUTES = {"objectClass": ["user"], "sAMAccountName": ["ann"]}
# The reply action the server sends for each request action.
REPLIES = {
    CREATE_ACTION: f"{WST}/CreateResponse",
    PUT_ACTION: f"{WST}/PutResponse",
    SET_PASSWORD_ACTION: f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse",
}


# Answers whichever write was asked for, so one script serves all three.
def replying(payload: bytes) -> bytes:
    request = ET.fromstring(decode_xml(payload))
    header = f"./{{{SOAP_ENV}}}Header"
    message_id = request.findtext(f"{header}/{{{WSA}}}MessageID") or ""
    action = request.findtext(f"{header}/{{{WSA}}}Action") or ""
    return encode_xml(
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:Action>{REPLIES[action]}</a:Action><a:RelatesTo>{message_id}</a:RelatesTo>'
        f'</s:Header><s:Body></s:Body></s:Envelope>')


# Fails whatever is asked after the create has already gone through.
def failing_after_create(payload: bytes) -> bytes:
    request = ET.fromstring(decode_xml(payload))
    header = f"./{{{SOAP_ENV}}}Header"
    action = request.findtext(f"{header}/{{{WSA}}}Action") or ""
    if action == CREATE_ACTION:
        return replying(payload)
    message_id = request.findtext(f"{header}/{{{WSA}}}MessageID") or ""
    return encode_xml(
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:RelatesTo>{message_id}</a:RelatesTo></s:Header><s:Body><s:Fault>'
        f'<s:Code><s:Value>s:Receiver</s:Value></s:Code><s:Reason>'
        f'<s:Text>password does not meet the complexity policy</s:Text>'
        f'</s:Reason></s:Fault></s:Body></s:Envelope>')


# The actions the client actually sent, in the order it sent them.
def actions(transport: object) -> List[str]:
    sent = transport.requests  # type: ignore[attr-defined]
    return [ET.fromstring(decode_xml(raw)).findtext(
        f"./{{{SOAP_ENV}}}Header/{{{WSA}}}Action") or "" for raw in sent]


# A usable account is three exchanges, and the order is forced by the directory.
def test_a_usable_account_is_created_then_given_a_password_then_enabled(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(monkeypatch, replying)
    reached = create_user(
        ADWSWriteClient("dc.example.test"),
        NewUser(ANN, ATTRIBUTES, password="Str0ng!Passw0rd", enable=True))
    assert actions(transport) == [CREATE_ACTION, SET_PASSWORD_ACTION, PUT_ACTION]
    assert reached == {"distinguishedName": ANN, "created": True,
                       "passwordSet": True, "enabled": True}


# The enable is the documented value, carried as an ordinary attribute replace.
def test_the_enable_sets_the_normal_account_flag(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(monkeypatch, replying)
    create_user(ADWSWriteClient("dc.example.test"),
                NewUser(ANN, ATTRIBUTES, password="Str0ng!Passw0rd", enable=True))
    put = ET.fromstring(decode_xml(transport.requests[2]))
    assert put.findtext(f".//{{{DA}}}AttributeType") == "addata:userAccountControl"
    assert put.findtext(f".//{{{AD}}}value") == ENABLED


# Without a password there is nothing to do after the create, and it says so.
def test_an_account_with_no_password_stops_after_the_create(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(monkeypatch, replying)
    reached = create_user(ADWSWriteClient("dc.example.test"),
                          NewUser(ANN, ATTRIBUTES))
    assert actions(transport) == [CREATE_ACTION]
    assert reached["created"] is True and reached["passwordSet"] is False
    assert reached["enabled"] is False


# Asking to enable without a password is refused before anything is sent.
def test_enabling_without_a_password_sends_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(monkeypatch, replying)
    with pytest.raises(ADWSClientError) as raised:
        create_user(ADWSWriteClient("dc.example.test"),
                    NewUser(ANN, ATTRIBUTES, enable=True))
    assert raised.value.code == "InvalidArgument"
    assert transport.requests == [], (
        "a request the directory would reject must not be sent; the account "
        "would exist and the caller would be told the whole thing failed")


# A failure after the create says the object exists, so a retry does not repeat it.
def test_a_failure_after_the_create_reports_what_was_left_behind(
        monkeypatch: pytest.MonkeyPatch) -> None:
    install_transport(monkeypatch, failing_after_create)
    with pytest.raises(ADWSClientError) as raised:
        create_user(ADWSWriteClient("dc.example.test"),
                    NewUser(ANN, ATTRIBUTES, password="weak", enable=True))
    assert "complexity policy" in raised.value.message
    assert "it exists, so a retry must not create it again" in raised.value.message
    assert "without a password" in raised.value.message
