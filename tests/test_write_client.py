"""Offline tests for the write client, over a scripted transport.

The request direction is checked in `test_write_request.py`, against the
server's own parsers. What is left is the client's own behaviour: what it does
with an answer, and what it does when the answer is not the one it asked for.

**The password has its own tests here** because the failure is silent. A client
that puts a password into an exception message writes it into whatever logs that
exception, and nothing about the resulting system looks wrong until somebody
reads the log.
"""

from typing import Optional

import pytest

from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient
from src.soap.namespaces import AD, SOAP_ENV
from tests.client_helpers import install_transport, response_for
from tests.scripted_transport import ScriptedTransport

SERVER = "dc.example.test"
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
ACCOUNT = "CN=jdoe," + PARENT
GUID = "4f2c8f16-0b64-4f0e-9c1a-3d8a5b2e7c91"
SECRET = "C0rrect-Horse-Battery"
CREATED = '<ad:objectReferenceProperty xmlns:ad="' + AD + '">' + GUID + \
          '</ad:objectReferenceProperty>'
EMPTY = '<ad:Nothing xmlns:ad="' + AD + '"/>'


# Installs a transport answering every request with one fixed body.
def answering(monkeypatch: pytest.MonkeyPatch, body: str,
              relates_to: str = "") -> ScriptedTransport:
    return install_transport(monkeypatch,
                             lambda payload: response_for(payload, body, relates_to))


# Installs a transport answering with a SOAP fault carrying one reason.
def faulting(monkeypatch: pytest.MonkeyPatch, reason: str,
             subcode: str = "ad:AccessDenied") -> ScriptedTransport:
    fault = ('<s:Fault xmlns:s="' + SOAP_ENV + '"><s:Code><s:Subcode><s:Value>' +
             subcode + '</s:Value></s:Subcode></s:Code><s:Reason><s:Text>' +
             reason + '</s:Text></s:Reason></s:Fault>')
    return answering(monkeypatch, fault)


# A created object is reported by the name it was given and the GUID it got.
def test_a_create_reports_the_name_and_the_identifier(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, CREATED)
    made = ADWSWriteClient(SERVER).create("CN=jdoe", PARENT, {"sAMAccountName": "jdoe"})
    assert made == {"distinguishedName": ACCOUNT, "objectGUID": GUID}
    assert len(transport.requests) == 1


# A create the server acknowledged without naming the object is not a success.
#
# The alternative is returning a record with an empty identifier, which a caller
# stores and comes back with later to find nothing there.
def test_a_create_with_no_identifier_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, EMPTY)
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).create("CN=jdoe", PARENT, {})
    assert raised.value.code == "ProtocolError"
    assert raised.value.target == PARENT


# A modify and a delete each take exactly one exchange.
@pytest.mark.parametrize("call", ["modify", "delete"])
def test_a_modify_and_a_delete_take_one_exchange(
        monkeypatch: pytest.MonkeyPatch, call: str) -> None:
    transport = answering(monkeypatch, EMPTY)
    client = ADWSWriteClient(SERVER)
    if call == "modify":
        client.modify(ACCOUNT, "sn", "Doe")
    else:
        client.delete(ACCOUNT)
    assert len(transport.requests) == 1


# An empty password is refused before anything reaches the network.
def test_an_empty_password_never_reaches_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, EMPTY)
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).set_password(ACCOUNT, "")
    assert raised.value.code == "InvalidArgument"
    assert transport.requests == []


# A refused password reset names the account and never the password.
def test_a_refused_password_is_not_in_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    faulting(monkeypatch, "Password does not meet the complexity requirements")
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).set_password(ACCOUNT, SECRET)
    error = raised.value
    assert error.target == ACCOUNT
    assert SECRET not in str(error)
    assert SECRET not in repr(error)


# A fault is raised with the code the server chose for it.
def test_a_fault_becomes_the_error_the_server_named(monkeypatch: pytest.MonkeyPatch) -> None:
    faulting(monkeypatch, "Insufficient access rights")
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).delete(ACCOUNT)
    assert raised.value.code == "AccessDenied"
    assert "Insufficient access rights" in str(raised.value)


# An answer to a different request is refused rather than read.
#
# A write client that accepted one would report a delete as having succeeded on
# the strength of an unrelated response.
def test_an_uncorrelated_answer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, EMPTY, relates_to="urn:uuid:00000000-0000-0000-0000-000000000000")
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER).delete(ACCOUNT)
    assert raised.value.code == "CorrelationError"


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
    transport = faulting(monkeypatch, reason) if reason else answering(monkeypatch, EMPTY)
    client = ADWSWriteClient(SERVER)
    if reason:
        with pytest.raises(ADWSClientError):
            client.delete(ACCOUNT)
    else:
        client.delete(ACCOUNT)
    assert transport.closed


# Connection settings are validated by the base client this one extends.
def test_a_write_client_still_checks_its_connection_settings() -> None:
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient("", 9389)
    assert raised.value.code == "InvalidArgument"
