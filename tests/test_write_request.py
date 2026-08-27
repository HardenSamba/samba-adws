"""Offline tests for the write requests, read back by the server's own parsers.

Every assertion below about what the client sends is made by handing the bytes
to the code in `classes/` that reads them on the other side. A test that parsed
the request with a reader written here would agree with itself, and the one
mistake it could never catch is the one where both halves of this repository are
wrong in the same way - which is the only interesting kind.

`BodyParser`, `AttributeParser` and `RequestContext` import nothing but
ElementTree, so they run on a workstation with no `ldb`. The routing table does
not: `handler_routing.py` imports every handler, so the one test that needs it
reads it with `ast` rather than importing it.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List

import pytest

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from samba_adws import _write_request as write
from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient

SERVER = "dc.example.test"
PORT = 9389
WHERE = write.Endpoint(SERVER, PORT)
ACCOUNTS = write.Endpoint(SERVER, PORT, write.ACCOUNT_PATH)
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
ACCOUNT = "CN=jdoe," + PARENT
ROUTING = Path(__file__).resolve().parents[1] / "src" / "handlers" / "handler_routing.py"


# Returns the entries the server reads out of an AddRequest this client built.
def added(rdn: str = "CN=jdoe", parent: str = PARENT,
          **attributes: object) -> List[Dict[str, Any]]:
    envelope, _ = write.build(WHERE, write.CREATE,
                              write.add_body(rdn, parent, attributes))
    return BodyParser(envelope).find_add_request() or []


# Returns one entry by name from what the server read, or fails the test.
def entry(entries: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    found = [item for item in entries if item["name"].lower() == name.lower()]
    assert found, "the server read no " + name + "; it read " + str(
        [item["name"] for item in entries])
    return found[0]


# Returns every literal string the routing module can resolve an action to.
def routable() -> List[str]:
    tree = ast.parse(ROUTING.read_text(encoding="utf-8"))
    keys: List[str] = []
    for node in ast.walk(tree):
        for key in getattr(node, "keys", []):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
        for item in getattr(node, "elts", []):
            first = item.elts[0] if isinstance(item, ast.Tuple) and item.elts else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.append(first.value)
    return keys


# Nothing this client can send arrives at a server with no handler for it.
def test_the_server_can_route_every_action_this_client_sends() -> None:
    known = routable()
    for action in (write.CREATE, write.PUT, write.DELETE, write.SET_PASSWORD):
        resolvable = action.lower() in known or action.rsplit("/", 1)[-1] in known
        assert resolvable, "nothing in handler_routing.py answers " + action


# The name and the parent arrive as the two fields the server composes a DN from.
def test_the_server_gets_the_two_halves_it_composes_a_name_from() -> None:
    entries = added()
    assert entry(entries, "relativeDistinguishedName")["values"] == ["CN=jdoe"]
    assert entry(entries, "container-hierarchy-parent")["values"] == [PARENT]


# A composed name is never sent: the server decides how a directory spells one.
def test_no_assembled_distinguished_name_is_sent() -> None:
    names = [item["name"].lower() for item in added()]
    assert "distinguishedname" not in names


# An ordinary attribute reaches the server under the name it was given.
def test_an_attribute_reaches_the_server_named_as_it_was_given() -> None:
    entries = added(sAMAccountName="jdoe", displayName="Jane Doe")
    assert entry(entries, "sAMAccountName")["values"] == ["jdoe"]
    assert entry(entries, "displayName")["values"] == ["Jane Doe"]


# Several values on one attribute all arrive.
def test_a_multi_valued_attribute_keeps_all_of_its_values() -> None:
    entries = added(otherTelephone=["1234", "5678"])
    assert entry(entries, "otherTelephone")["values"] == ["1234", "5678"]


# A value carrying markup is read back as the characters that were given.
#
# This is the whole of the escaping: an unescaped ampersand produces a request
# the server cannot parse, and an unescaped angle bracket produces one it parses
# differently from what was meant.
def test_a_value_carrying_markup_survives_intact() -> None:
    given = 'Ops & Co <lab> "quoted"'
    assert entry(added(description=given), "description")["values"] == [given]


# A name carrying markup survives too, which is the half a test usually misses.
def test_a_name_carrying_markup_survives_intact() -> None:
    entries = added(rdn="CN=R&D <core>")
    assert entry(entries, "relativeDistinguishedName")["values"] == ["CN=R&D <core>"]


# A modify is read as a replacement of the one attribute it names.
def test_a_modify_is_read_as_a_replace_of_one_attribute() -> None:
    envelope, _ = write.build(WHERE, write.PUT,
                              write.modify_body("userAccountControl", 512), ACCOUNT)
    changes = BodyParser(envelope).find_modify_request() or []
    assert [(c["name"], c["operation"], c["values"]) for c in changes] == [
        ("userAccountControl", "replace", ["512"])
    ]


# The password body is the element the server's SetPassword handler looks for.
def test_the_password_body_is_the_one_set_password_reads() -> None:
    envelope, _ = write.build(ACCOUNTS, write.SET_PASSWORD,
                              write.password_body(ACCOUNT, "C0rrect-Horse"))
    parser = BodyParser(envelope)
    body = parser.find_custom_body("SetPasswordRequest")
    assert body is not None
    assert parser.text_of(body, "AccountDN") == ACCOUNT
    assert parser.text_of(body, "NewPassword") == "C0rrect-Horse"


# Setting a password is addressed to the endpoint that accepts the action.
def test_a_password_is_addressed_to_the_account_management_endpoint() -> None:
    envelope, _ = write.build(ACCOUNTS, write.SET_PASSWORD,
                              write.password_body(ACCOUNT, "C0rrect-Horse"))
    other, _ = write.build(WHERE, write.PUT, write.modify_body("sn", "Doe"), ACCOUNT)
    assert write.ACCOUNT_PATH in envelope
    assert write.ACCOUNT_PATH not in other


# A delete names its target where the delete handler reads one.
def test_a_delete_names_its_target_where_the_handler_reads_it() -> None:
    envelope, message_id = write.build(WHERE, write.DELETE, "", ACCOUNT)
    context = RequestContext.from_xml(envelope)
    assert context.object_reference == ACCOUNT
    assert context.message_id == message_id
    assert context.action == write.DELETE


# A create names no target, because the object does not exist yet.
def test_a_create_names_no_target() -> None:
    envelope, _ = write.build(WHERE, write.CREATE,
                              write.add_body("CN=jdoe", PARENT, {}))
    assert RequestContext.from_xml(envelope).object_reference in (None, "")


# Two requests never carry the same MessageID.
#
# The correlation check in `_envelope.read_body` is only worth having while the
# identifiers differ; repeating one would let a stale response satisfy it.
def test_each_request_is_correlated_by_its_own_identifier() -> None:
    made = {write.build(WHERE, write.DELETE, "", ACCOUNT)[1] for _ in range(20)}
    assert len(made) == 20


# An identity the client cannot use is refused before anything is built.
@pytest.mark.parametrize("identity", ["", "   "])
def test_an_empty_identity_is_refused_before_the_wire(identity: str) -> None:
    client = ADWSWriteClient(SERVER, PORT)
    with pytest.raises(ADWSClientError) as raised:
        client.delete(identity)
    assert raised.value.code == "InvalidArgument"
