"""Offline tests for the membership Put, read back by the server's own parser.

The claim `#21` rests on is that `add_member` and `remove_member` reach the
directory as a delta, never as a replace. The only reader whose opinion counts
is the server's: `BodyParser` is what `ModifyHandler` reads the request with,
and `tests/unit/test_group_membership_write_path.py` already pins what it reads
out of the Put that `Add-ADGroupMember` sends. So the assertion here is not
"the XML looks right" but "the server reads from this client exactly what it
reads from the cmdlet", entry for entry.
"""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import pytest
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from samba_adws._member_request import ADD, REMOVE, Membership, build_member_request
from samba_adws._request import RESOURCE_PATH
from samba_adws._write_request import PUT_ACTION

from tests.unit.test_group_membership_write_path import GROUP_DN, MEMBER_DN, put_envelope

SERVER = "dc.example.test"
PORT = 9389
WSA = "{http://www.w3.org/2005/08/addressing}"


# The envelope this client builds for one membership operation.
def built(operation: str) -> str:
    envelope, _ = build_member_request(SERVER, PORT, Membership(GROUP_DN, MEMBER_DN),
                                       operation)
    return envelope


# What the server reads out of a ModifyRequest, however it was produced.
def read(envelope: str) -> List[Dict[str, Any]]:
    return BodyParser(envelope).find_modify_request() or []


# The server reads one change on member, carrying the operation, and nothing else.
@pytest.mark.parametrize("operation", [ADD, REMOVE])
def test_the_server_reads_one_member_change_with_its_operation(operation: str) -> None:
    assert read(built(operation)) == [
        {"name": "member", "operation": operation, "values": [MEMBER_DN]}
    ]


# Entry for entry, it is what the cmdlet's recorded Put parses to.
#
# This is the equivalence the module exists for: a consumer of this client and
# an administrator running Add-ADGroupMember put the same thing on the wire.
@pytest.mark.parametrize("operation", [ADD, REMOVE])
def test_it_parses_to_what_the_cmdlet_sends(operation: str) -> None:
    assert read(built(operation)) == read(put_envelope(operation))


# It is a WS-Transfer Put, in the IMDA dialect, addressed to the group.
def test_it_is_a_put_addressed_to_the_group() -> None:
    envelope = built(ADD)
    context = RequestContext.from_xml(envelope)
    assert context.action == PUT_ACTION
    assert context.object_reference == GROUP_DN
    assert context.is_imda
    to = ET.fromstring(envelope).findtext(f".//{WSA}To") or ""
    assert to.endswith(RESOURCE_PATH)


# A replace never leaves this builder, whichever verb asked.
#
# It is the whole point: a replace on member is the lost update `#21` describes.
@pytest.mark.parametrize("operation", [ADD, REMOVE])
def test_a_replace_is_never_sent(operation: str) -> None:
    assert 'Operation="replace"' not in built(operation)
