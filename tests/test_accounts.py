"""Offline tests for the order the three exchanges go in.

`accounts.py` exists because the order is the knowledge, so the order is what
these check: which actions went out, in which sequence, and what the caller was
told about how far it got.

The actions are read back out of the recorded traffic with the server's own
`RequestContext`, not with a note the client made about what it had sent. A
record of an intention is not evidence of a request.
"""

from typing import Any, Dict, List, Tuple

import pytest

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from samba_adws import _write_request as write
from samba_adws._codec import decode_xml
from samba_adws.accounts import ENABLED, NewUser, create_user
from samba_adws.write_client import ADWSWriteClient
from src.soap.namespaces import AD
from tests.client_helpers import install_transport, response_for
from tests.scripted_transport import ScriptedTransport

SERVER = "dc.example.test"
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
ACCOUNT = "CN=jdoe," + PARENT
GUID = "4f2c8f16-0b64-4f0e-9c1a-3d8a5b2e7c91"
SECRET = "C0rrect-Horse-Battery"

# The two userAccountControl bits this file reasons about, from [MS-ADTS]
# 2.2.16: ADS_UF_ACCOUNTDISABLE and ADS_UF_NORMAL_ACCOUNT. Written here rather
# than imported, because a test that reads the constant the code reads agrees
# with the code about a wrong value.
DISABLED_BIT = 0x0002
NORMAL_ACCOUNT_BIT = 0x0200
CREATED = '<ad:objectReferenceProperty xmlns:ad="' + AD + '">' + GUID + \
          '</ad:objectReferenceProperty>'
EMPTY = '<ad:Nothing xmlns:ad="' + AD + '"/>'


# Installs a transport that acknowledges a create and accepts everything else.
def accepting(monkeypatch: pytest.MonkeyPatch) -> ScriptedTransport:
    def answer(payload: bytes) -> bytes:
        creating = "AddRequest" in decode_xml(payload)
        return response_for(payload, CREATED if creating else EMPTY)

    return install_transport(monkeypatch, answer)


# Returns the actions that actually went out, in the order they went.
def actions(transport: ScriptedTransport) -> List[str]:
    return [RequestContext.from_xml(decode_xml(sent)).action for sent in transport.requests]


# Runs one create through a scripted transport and returns both halves.
def made(monkeypatch: pytest.MonkeyPatch,
         wanted: NewUser) -> Tuple[Dict[str, Any], ScriptedTransport]:
    transport = accepting(monkeypatch)
    return create_user(ADWSWriteClient(SERVER), wanted), transport


# An account asked for without a password is one exchange and says so.
def test_no_password_is_one_exchange_and_an_honest_report(
        monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(monkeypatch, NewUser("jdoe", PARENT, {"sn": "Doe"}))
    assert actions(transport) == [write.CREATE]
    assert account["distinguishedName"] == ACCOUNT
    assert account["passwordSet"] is False
    assert account["enabled"] is False


# A password is set after the object exists, never before and never with it.
def test_a_password_follows_the_create(monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(monkeypatch, NewUser("jdoe", PARENT, {}, password=SECRET))
    assert actions(transport) == [write.CREATE, write.SET_PASSWORD]
    assert account["passwordSet"] is True
    assert account["enabled"] is False


# Enabling comes last, because a directory refuses an account with no password.
def test_enabling_comes_after_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(
        monkeypatch, NewUser("jdoe", PARENT, {}, password=SECRET, enable=True))
    assert actions(transport) == [write.CREATE, write.SET_PASSWORD, write.PUT]
    assert account["passwordSet"] is True
    assert account["enabled"] is True


# The last exchange clears the disabled bit and nothing else.
def test_the_enabling_exchange_sets_the_account_control(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(
        monkeypatch, NewUser("jdoe", PARENT, {}, password=SECRET, enable=True))
    last = decode_xml(transport.requests[-1])
    changes = BodyParser(last).find_modify_request() or []
    assert [(c["name"], c["values"]) for c in changes] == [
        ("userAccountControl", ["512"])
    ]


# The value sent to enable an account is a normal account with the bit clear.
#
# Asserting `str(ENABLED)` above would have read the same constant the code
# reads, so any value at all would have passed. This says what makes 512 right:
# the disabled bit is off and the normal-account bit is on, and nothing else.
def test_the_enabled_value_is_a_normal_account_that_is_not_disabled() -> None:
    assert ENABLED & DISABLED_BIT == 0
    assert ENABLED & NORMAL_ACCOUNT_BIT == NORMAL_ACCOUNT_BIT
    assert ENABLED & ~NORMAL_ACCOUNT_BIT == 0


# Asking to enable an account with no password enables nothing.
#
# The directory would refuse it, so the request is not sent and the caller is
# told the account is disabled rather than being told it succeeded.
def test_enabling_without_a_password_is_not_attempted(
        monkeypatch: pytest.MonkeyPatch) -> None:
    account, transport = made(monkeypatch, NewUser("jdoe", PARENT, {}, enable=True))
    assert actions(transport) == [write.CREATE]
    assert account["enabled"] is False


# The password is in the exchange that sets it and in no other.
#
# Folding it into the create would send it where the server does not read it:
# the account would exist, the caller would be told the password was set, and
# nobody would find out until the account failed to sign in.
def test_the_password_is_only_in_the_exchange_that_sets_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(
        monkeypatch, NewUser("jdoe", PARENT, {}, password=SECRET, enable=True))
    carrying = [SECRET in decode_xml(sent) for sent in transport.requests]
    assert carrying == [False, True, False]


# What the caller gets back never carries the password onward.
def test_the_report_does_not_carry_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    account, _ = made(
        monkeypatch, NewUser("jdoe", PARENT, {}, password=SECRET, enable=True))
    assert SECRET not in str(account)


# The attributes the caller asked for reach the create.
def test_the_requested_attributes_reach_the_create(
        monkeypatch: pytest.MonkeyPatch) -> None:
    attributes: Dict[str, object] = {"sAMAccountName": "jdoe", "displayName": "Jane Doe"}
    _, transport = made(monkeypatch, NewUser("jdoe", PARENT, attributes))
    entries = BodyParser(decode_xml(transport.requests[0])).find_add_request() or []
    read = {item["name"]: item["values"] for item in entries}
    assert read["sAMAccountName"] == ["jdoe"]
    assert read["displayName"] == ["Jane Doe"]


# The name is prefixed once, by this layer, and reaches the server as a name.
def test_the_relative_name_is_composed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _, transport = made(monkeypatch, NewUser("jdoe", PARENT, {}))
    entries = BodyParser(decode_xml(transport.requests[0])).find_add_request() or []
    read = {item["name"].lower(): item["values"] for item in entries}
    assert read["relativedistinguishedname"] == ["CN=jdoe"]
