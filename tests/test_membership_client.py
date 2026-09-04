"""Offline tests for the membership client, over a scripted transport.

The request direction is checked in `test_member_request.py` against the
server's own parser. What is left is the client's behaviour: one exchange per
call, an empty PutResponse read as success, a directory refusal reported with
the group as the target, and a bad identity refused before anything is sent.

The scripted answers and the faults are the ones `test_write_client.py` builds,
for the reasons that file gives: an empty body is what a real PutResponse is,
and a fault built by `FaultBuilder` is one a handler can actually send.
"""

import pytest
from classes.parsing.body_parser import BodyParser
from samba_adws import ADWSClientError, ADWSMembershipClient
from samba_adws._codec import decode_xml

from tests.test_write_client import PUT_RESPONSE, answering, directory_fault, faulting

SERVER = "dc.example.test"
GROUP = "CN=Demo Group,CN=Users,DC=example,DC=test"
MEMBER = "CN=userA,CN=Users,DC=example,DC=test"
ALREADY = "Attribute member already exists for target GUID 86491db9"


# The operation the server would read out of the one request a call sent.
def sent_operation(requests: list) -> str:  # type: ignore[type-arg]
    assert len(requests) == 1, f"expected one exchange, saw {len(requests)}"
    entries = BodyParser(decode_xml(requests[0])).find_modify_request() or []
    assert [e["name"] for e in entries] == ["member"]
    return str(entries[0]["operation"])


# add_member is one Put carrying an add, and an empty PutResponse is success.
def test_add_member_sends_one_add_and_accepts_an_empty_response(
        monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, PUT_RESPONSE)
    assert ADWSMembershipClient(SERVER).add_member(GROUP, MEMBER) is None
    assert sent_operation(transport.requests) == "add"


# remove_member is one Put carrying a delete.
def test_remove_member_sends_one_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = answering(monkeypatch, PUT_RESPONSE)
    ADWSMembershipClient(SERVER).remove_member(GROUP, MEMBER)
    assert sent_operation(transport.requests) == "delete"


# A refusal arrives as ModifyFailed, names the group, and keeps the reason.
#
# The reason is the directory's own sentence for a redundant add, which is what
# a caller has to show: the code alone cannot tell "already a member" from any
# other refused modify.
def test_a_refusal_names_the_group_and_keeps_the_reason(
        monkeypatch: pytest.MonkeyPatch) -> None:
    faulting(monkeypatch, directory_fault(ALREADY, "ModifyFailed"))
    with pytest.raises(ADWSClientError) as raised:
        ADWSMembershipClient(SERVER).add_member(GROUP, MEMBER)
    assert raised.value.code == "ModifyFailed"
    assert raised.value.target == GROUP
    assert ALREADY in str(raised.value)


# An empty identity on either side is refused before anything reaches the wire.
@pytest.mark.parametrize("group,member", [("", MEMBER), (GROUP, ""), ("  ", MEMBER)])
def test_a_blank_identity_is_refused_before_sending(
        monkeypatch: pytest.MonkeyPatch, group: str, member: str) -> None:
    transport = answering(monkeypatch, PUT_RESPONSE)
    with pytest.raises(ADWSClientError):
        ADWSMembershipClient(SERVER).add_member(group, member)
    assert transport.requests == []
