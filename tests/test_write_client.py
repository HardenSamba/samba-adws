"""Offline tests for the write client, over a scripted transport.

The request direction is checked in `test_write_request.py`, against the
server's own parsers. What is left is this client's own behaviour: what it does
with an answer, and what it does when the answer is not the one it asked for.

**The scripted answer carries an empty body by default, and that is the point.**
`classes/handlers/modify.py` and `classes/handlers/delete.py` both answer a
success with `envelope.wrap(REPLY_ACTION, message_id, "")`. A fixture that put a
filler element in every body — or that answered every write with a WS-Transfer
GetResponse — would let a client which demands a non-empty body pass its whole
suite while reporting failure for every rename and every delete the directory
had already performed.

**The password has tests of its own** because the failure is silent. A client
that puts a secret in an exception message writes it into whatever logs that
exception, and nothing about the resulting system looks wrong until somebody
reads the log.

**The faults are built by the server's own `FaultBuilder`**, for the same reason
the request tests are read back by the server's own parsers. A fault hand-rolled
here can carry a subcode no handler ever sends, and the client is then asserted
to report a code that cannot reach it in production — filler on the failure path
is the same defect as filler on the success path. `classes.faults.faults` and
`classes.soap.soap_envelope` import no `ldb`, so this costs nothing offline.
"""

import functools
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import pytest
from classes.faults.faults import FaultBuilder
from samba_adws import ADWSClientError, ADWSWriteClient
from samba_adws._codec import decode_xml, encode_xml
from src.soap.namespaces import AD, CUSTOM_ACTIONS, SOAP_ENV, WSA, WST

from tests.client_helpers import install_transport
from tests.scripted_transport import ScriptedTransport

SERVER = "dc.example.test"
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
ACCOUNT = "CN=jdoe," + PARENT
GUID = "4f2c8f16-0b64-4f0e-9c1a-3d8a5b2e7c91"
SECRET = "C0rrect-Horse-Battery"
CREATE_RESPONSE = f"{WST}/CreateResponse"
PUT_RESPONSE = f"{WST}/PutResponse"
DELETE_RESPONSE = f"{WST}/DeleteResponse"
SET_PASSWORD_RESPONSE = f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse"
# The EPR `CreateHandler._success` replies with, reduced to the element read.
CREATED = (f'<wst:ResourceCreated xmlns:wst="{WST}" xmlns:ad="{AD}">'
           f'<ad:objectReferenceProperty>{GUID}</ad:objectReferenceProperty>'
           f'</wst:ResourceCreated>')


# Returns the MessageID of a scripted request, which a real answer relates to.
def message_id_of(payload: bytes) -> str:
    request = ET.fromstring(decode_xml(payload))
    return request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""


# Builds a correlated write response carrying the given reply action and body.
#
# The body defaults to empty because that is what a PutResponse and a
# DeleteResponse actually are.
def write_response(payload: bytes, action: str, body: str = "",
                   relates_to: str = "") -> bytes:
    xml = (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}"><s:Header>'
        f'<a:Action>{action}</a:Action>'
        f'<a:RelatesTo>{relates_to or message_id_of(payload)}</a:RelatesTo>'
        f'</s:Header><s:Body>{body}</s:Body></s:Envelope>'
    )
    return encode_xml(xml)


# Installs a transport answering every request with one action and body.
def answering(monkeypatch: pytest.MonkeyPatch, action: str, body: str = "",
              relates_to: str = "") -> ScriptedTransport:
    return install_transport(monkeypatch, functools.partial(
        write_response, action=action, body=body, relates_to=relates_to))


# Installs a transport answering with a fault this server would really build.
#
# `build` is the `FaultBuilder` classmethod the handler under test calls, bound
# to everything but the correlation identifier. The envelope it returns declares
# the WS-Addressing *fault* action, not the reply action, which is also what
# makes these tests pin the check order: reading the fault before the action is
# what stops a genuine refusal from being reported as MalformedResponse.
def faulting(monkeypatch: pytest.MonkeyPatch,
             build: Callable[[str], str]) -> ScriptedTransport:
    def answer(payload: bytes) -> bytes:
        return encode_xml(build(message_id_of(payload)))

    return install_transport(monkeypatch, answer)


# The fault a create, modify, delete or rename failure really produces.
#
# `FaultBuilder.directory_error` sets no SOAP subcode at all: the discriminator
# is `da:ShortError` inside the fault Detail, and it is the only thing that tells
# a refused create from a refused delete.
def directory_fault(reason: str, short_error: str) -> Callable[[str], str]:
    return lambda relates_to: str(
        FaultBuilder.directory_error(relates_to, reason, short_error))


# The fault a SetPassword failure really produces, which does carry a subcode.
def password_fault(reason: str) -> Callable[[str], str]:
    return lambda relates_to: str(
        FaultBuilder.custom_action_fault(relates_to, "SetPasswordFault", reason))


# Returns the parsed request the client sent to the scripted transport.
def sent(transport: ScriptedTransport, index: int = 0) -> ET.Element:
    return ET.fromstring(decode_xml(transport.requests[index]))


# A modify and a delete succeed on the empty body the handlers actually send.
#
# This is the regression that matters most in this file. Routing a write through
# `_envelope.read_body` raises `MalformedResponse` here, so the caller is told
# the write failed after the directory has already done it.
@pytest.mark.parametrize("verb,action", [("modify", PUT_RESPONSE),
                                         ("rename", PUT_RESPONSE),
                                         ("delete", DELETE_RESPONSE)])
def test_an_empty_response_body_is_a_success(
        monkeypatch: pytest.MonkeyPatch, verb: str, action: str) -> None:
    transport = answering(monkeypatch, action)
    client = ADWSWriteClient(SERVER)
    if verb == "modify":
        client.modify(ACCOUNT, {"sn": ["Doe"]})
    elif verb == "rename":
        client.rename(ACCOUNT, new_rdn="CN=jane")
    else:
        client.delete(ACCOUNT)
    assert len(transport.requests) == 1


# A created object is reported by the identifier the directory gave it.
def test_a_create_reports_the_identifier_the_directory_gave(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, CREATE_RESPONSE, CREATED)
    made = ADWSWriteClient(SERVER).create("CN=jdoe", PARENT, {"sAMAccountName": ["jdoe"]})
    assert made == GUID
    assert len(transport.requests) == 1


# A create the server acknowledged without naming the object is not a success.
#
# The alternative is returning an empty identifier, which a caller stores and
# comes back with later to find nothing there.
def test_a_create_with_no_identifier_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, CREATE_RESPONSE)
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).create("CN=jdoe", PARENT, {"sn": ["Doe"]})
    assert raised.value.code == "ProtocolError"
    assert raised.value.target == PARENT


# A response declaring the wrong reply action is refused, not accepted.
#
# Without this the action check is deletable with every other test still green,
# and a Delete would be satisfied by an acknowledgement of something else.
def test_a_response_declaring_the_wrong_action_is_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, PUT_RESPONSE)
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).delete(ACCOUNT)
    assert raised.value.code == "MalformedResponse"


# An answer to a different request is refused rather than read.
def test_an_uncorrelated_answer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, DELETE_RESPONSE, relates_to="urn:uuid:nope")
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).delete(ACCOUNT)
    assert raised.value.code == "CorrelationError"


# A fault is raised with the code the server chose for it, verb by verb.
#
# The codes below are the literal third arguments `CreateHandler`, `ModifyHandler`
# and `DeleteHandler` pass to `directory_error`. None of them reaches a subcode,
# so a client that reads only the subcode reports "SOAPFault" for all three and
# a caller cannot tell which operation the directory refused, or why.
@pytest.mark.parametrize("verb,short_error,target", [
    ("create", "CreateFailed", PARENT),
    ("modify", "ModifyFailed", ACCOUNT),
    ("delete", "DeleteFailed", ACCOUNT),
])
def test_a_fault_becomes_the_error_the_server_named(
        monkeypatch: pytest.MonkeyPatch, verb: str, short_error: str, target: str) -> None:
    faulting(monkeypatch, directory_fault("Insufficient access rights", short_error))
    client = ADWSWriteClient(SERVER)
    calls = {"create": lambda: client.create("CN=jdoe", PARENT, {"sn": ["Doe"]}),
             "modify": lambda: client.modify(ACCOUNT, {"sn": ["Doe"]}),
             "delete": lambda: client.delete(ACCOUNT)}
    with pytest.raises(ADWSClientError) as raised:
        calls[verb]()
    assert raised.value.code == short_error
    assert "Insufficient access rights" in str(raised.value)
    assert raised.value.target == target


# A fault that does carry a subcode is still read from the subcode.
#
# `SetPasswordHandler` is the one write path that uses `custom_action_fault`, so
# it is the one that proves the Detail is a fallback and not a replacement.
def test_a_subcode_still_wins_over_the_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    faulting(monkeypatch, password_fault("Password does not meet the requirements"))
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).set_password(ACCOUNT, SECRET)
    assert raised.value.code == "SetPasswordFault"


# The secret rides the sealed body and never appears in a header.
def test_the_secret_is_in_the_body_and_not_in_the_header(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, SET_PASSWORD_RESPONSE,
                          f'<SetPasswordResponse xmlns="{CUSTOM_ACTIONS}"/>')
    ADWSWriteClient(SERVER).set_password(ACCOUNT, SECRET)
    root = sent(transport)
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    assert header is not None
    assert root.findtext(f".//{{{CUSTOM_ACTIONS}}}NewPassword") == SECRET
    assert SECRET not in ET.tostring(header, encoding="unicode")


# A refused password reset names the account and never the password.
def test_a_refused_password_is_not_in_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    faulting(monkeypatch, password_fault(
        "Password does not meet the complexity requirements"))
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).set_password(ACCOUNT, SECRET)
    assert raised.value.target == ACCOUNT
    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value)


# A transport that fails is reported as a transport failure against the target.
def test_a_transport_failure_names_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_: bytes) -> bytes:
        raise OSError("connection refused")

    install_transport(monkeypatch, refuse)
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).delete(ACCOUNT)
    assert raised.value.code == "TransportError"
    assert raised.value.target == ACCOUNT


# The session is closed whether the exchange succeeded or faulted.
@pytest.mark.parametrize("reason", [None, "Insufficient access rights"])
def test_the_session_is_closed_either_way(
        monkeypatch: pytest.MonkeyPatch, reason: Optional[str]) -> None:
    transport = (faulting(monkeypatch, directory_fault(reason, "DeleteFailed")) if reason
                 else answering(monkeypatch, DELETE_RESPONSE))
    client = ADWSWriteClient(SERVER)
    if reason:
        with pytest.raises(ADWSClientError):
            client.delete(ACCOUNT)
    else:
        client.delete(ACCOUNT)
    assert transport.closed


# Bad inputs are rejected before any network exchange occurs.
def test_validation_rejects_bad_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, PUT_RESPONSE)
    client = ADWSWriteClient(SERVER)
    with pytest.raises(ADWSClientError):
        client.create("CN=Ann", PARENT, {"cn": "not-a-sequence"})
    with pytest.raises(ADWSClientError):
        client.rename(ACCOUNT, new_rdn="   ")
    with pytest.raises(ADWSClientError):
        client.set_password(ACCOUNT, "")
    with pytest.raises(ADWSClientError):
        client.modify(ACCOUNT, {"sn": [b"bytes"]})  # type: ignore[list-item]
    assert transport.requests == []


# Connection settings are validated by the base client this one extends.
def test_a_write_client_still_checks_its_connection_settings() -> None:
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient("", 9389)
    assert raised.value.code == "InvalidArgument"
