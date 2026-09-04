"""Offline tests for the order the three exchanges go in.

`accounts.py` exists because the order is the knowledge, so the order is what
these check: which actions went out, in which sequence, what each carried, and
what the caller was told when one of them was refused.

**The actions are read back out of the recorded traffic** with the server's
own `RequestContext` and `BodyParser`, never from a note the client made about
what it meant to send. A record of an intention is not evidence of a request.

**The two `userAccountControl` values are checked bit by bit** against
constants written in this file from [MS-ADTS] 2.2.16, not imported from the
module under test. A test that reads the constant the code reads agrees with
the code about a wrong value: `514` is the disabled bit *set*, and it passed a
suite that asserted `str(ENABLED)`.
"""

import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from classes.faults.faults import FaultBuilder
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from samba_adws import Account, AccountLeftDisabled, ADWSClientError, Placement
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._write_request import CREATE_ACTION, PUT_ACTION, SET_PASSWORD_ACTION
from samba_adws.accounts import CREATED, PASSWORD_SET, USABLE, create_usable_account
from samba_adws.write_client import ADWSWriteClient
from src.soap.namespaces import AD, SOAP_ENV, WSA

from tests.client_helpers import install_transport
from tests.scripted_transport import ScriptedTransport
from tests.test_write_client import (
    CREATE_RESPONSE,
    PUT_RESPONSE,
    SET_PASSWORD_RESPONSE,
    message_id_of,
)

SERVER = "dc.example.test"
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
RDN = "CN=Doe\\, Jane"
DN = RDN + "," + PARENT
GUID = "4f2c8f16-0b64-4f0e-9c1a-3d8a5b2e7c91"
SECRET = "C0rrect-Horse-Battery"

# [MS-ADTS] 2.2.16, written here rather than imported.
DISABLED_BIT = 0x0002
PASSWORD_NOT_REQUIRED_BIT = 0x0020
NORMAL_ACCOUNT_BIT = 0x0200

REPLY = {CREATE_ACTION: CREATE_RESPONSE, SET_PASSWORD_ACTION: SET_PASSWORD_RESPONSE,
         PUT_ACTION: PUT_RESPONSE}
CREATED_BODY = (f'<ad:objectReferenceProperty xmlns:ad="{AD}">{GUID}'
                f'</ad:objectReferenceProperty>')
Entries = Optional[List[Dict[str, Any]]]


# The action a scripted request carries, read the way the server reads it.
def action_of(payload: bytes) -> str:
    return RequestContext.from_xml(decode_xml(payload)).action


# A server that acknowledges each of the three verbs with its own reply action,
# and refuses the one named with a fault the real handler would build.
def scripted(monkeypatch: pytest.MonkeyPatch,
             refuse: Optional[str] = None) -> ScriptedTransport:
    def answer(payload: bytes) -> bytes:
        action, relates_to = action_of(payload), message_id_of(payload)
        if action == refuse:
            fault = FaultBuilder.directory_error(relates_to, "refused by the test",
                                                 "ModifyFailed")
            return encode_xml(str(fault))
        body = CREATED_BODY if action == CREATE_ACTION else ""
        return encode_xml(
            f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
            f'<a:Action>{REPLY[action]}</a:Action><a:RelatesTo>{relates_to}</a:RelatesTo>'
            f'</s:Header><s:Body>{body}</s:Body></s:Envelope>')

    return install_transport(monkeypatch, answer)


# The actions that actually went out, in the order they went.
def actions(transport: ScriptedTransport) -> List[str]:
    return [action_of(sent) for sent in transport.requests]


# The one userAccountControl value the server would read out of a request.
def control_in(payload: bytes, read: Callable[[BodyParser], Entries]) -> int:
    entries = read(BodyParser(decode_xml(payload))) or []
    values = [e["values"] for e in entries if e["name"].lower() == "useraccountcontrol"]
    assert len(values) == 1, "expected exactly one userAccountControl"
    return int(values[0][0])


# Runs the sequence against an accepting server and returns both halves.
def made(monkeypatch: pytest.MonkeyPatch) -> Tuple[Account, ScriptedTransport]:
    transport = scripted(monkeypatch)
    account = create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT),
                                    {"sAMAccountName": ("jdoe",)}, SECRET)
    return account, transport


# Create, then the password, then the enable. Read off the wire, in that order.
def test_the_three_exchanges_go_out_in_the_forced_order(
        monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(monkeypatch)
    assert actions(transport) == [CREATE_ACTION, SET_PASSWORD_ACTION, PUT_ACTION]
    assert account == Account(DN, GUID, USABLE)


# The create carries a disabled normal account allowed to have no password yet.
def test_the_create_is_disabled_whatever_the_caller_asked(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(monkeypatch)
    control = control_in(transport.requests[0], BodyParser.find_add_request)
    assert control & DISABLED_BIT == DISABLED_BIT
    assert control & PASSWORD_NOT_REQUIRED_BIT == PASSWORD_NOT_REQUIRED_BIT
    assert control & NORMAL_ACCOUNT_BIT == NORMAL_ACCOUNT_BIT
    assert control & ~(DISABLED_BIT | PASSWORD_NOT_REQUIRED_BIT | NORMAL_ACCOUNT_BIT) == 0


# The enable clears the disabled bit, requires a password, and sets nothing else.
def test_the_enable_is_a_normal_account_that_is_not_disabled(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(monkeypatch)
    control = control_in(transport.requests[2], BodyParser.find_modify_request)
    assert control & DISABLED_BIT == 0
    assert control & PASSWORD_NOT_REQUIRED_BIT == 0
    assert control & NORMAL_ACCOUNT_BIT == NORMAL_ACCOUNT_BIT
    assert control & ~NORMAL_ACCOUNT_BIT == 0


# The password is in the exchange that sets it and in no other.
def test_the_password_is_only_in_the_exchange_that_sets_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(monkeypatch)
    assert [SECRET in decode_xml(sent) for sent in transport.requests] == [False, True, False]
    assert SECRET not in str(account)


# The relative name reaches the server as the caller spelled it, comma and all,
# and the exchanges after the create name the object by the two halves joined.
def test_the_relative_name_is_the_callers_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(monkeypatch)
    entries = BodyParser(decode_xml(transport.requests[0])).find_add_request() or []
    read = {e["name"].lower(): e["values"] for e in entries}
    assert read["relativedistinguishedname"] == [RDN]
    assert read["container-hierarchy-parent"] == [PARENT]
    later = ET.fromstring(decode_xml(transport.requests[2]))
    assert later.findtext(f".//{{{AD}}}objectReferenceProperty") == DN


# A caller supplying userAccountControl is refused before anything is sent.
def test_a_supplied_account_control_is_refused_before_the_create(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = scripted(monkeypatch)
    with pytest.raises(ADWSClientError) as raised:
        create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT),
                              {"userAccountControl": ("512",)}, SECRET)
    assert raised.value.code == "InvalidArgument"
    assert transport.requests == []


# An empty password is refused before the create, so no object is left behind.
def test_an_empty_password_is_refused_before_the_create(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = scripted(monkeypatch)
    with pytest.raises(ADWSClientError):
        create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT), {}, "")
    assert transport.requests == []


# A refused password leaves a disabled account, and the error says exactly that.
#
# This is the property the module exists for: the enable is never sent, so what
# is left is inert, and the caller is told where it is and how far it got.
def test_a_refused_password_reports_the_disabled_account(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = scripted(monkeypatch, refuse=SET_PASSWORD_ACTION)
    with pytest.raises(AccountLeftDisabled) as raised:
        create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT), {}, SECRET)
    assert actions(transport) == [CREATE_ACTION, SET_PASSWORD_ACTION]
    assert raised.value.account == Account(DN, GUID, CREATED)
    assert raised.value.target == DN
    assert raised.value.code == "ModifyFailed"
    assert SECRET not in str(raised.value)


# A refused enable reports that the password was set, so a retry starts there.
def test_a_refused_enable_reports_the_password_was_set(
        monkeypatch: pytest.MonkeyPatch) -> None:
    scripted(monkeypatch, refuse=PUT_ACTION)
    with pytest.raises(AccountLeftDisabled) as raised:
        create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT), {}, SECRET)
    assert raised.value.account.reached == PASSWORD_SET


# A refused create is the write client's own error: nothing was left behind.
def test_a_refused_create_leaves_nothing_and_is_not_dressed_up(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = scripted(monkeypatch, refuse=CREATE_ACTION)
    with pytest.raises(ADWSClientError) as raised:
        create_usable_account(ADWSWriteClient(SERVER), Placement(RDN, PARENT), {}, SECRET)
    assert not isinstance(raised.value, AccountLeftDisabled)
    assert actions(transport) == [CREATE_ACTION]
