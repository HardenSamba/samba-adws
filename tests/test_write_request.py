"""Offline tests for the write requests, read back by the server's own parsers.

Every assertion below about what the client sends is made by handing the bytes
to the code in `classes/` that reads them on the other side. A test that parsed
the request with a reader written here would agree with itself, and the one
mistake it could never catch is the one where both halves of this repository are
wrong in the same way — which is the only interesting kind.

`BodyParser`, `AttributeParser` and `RequestContext` import nothing but
ElementTree, so they run on a workstation with no `ldb`. The routing table does
not: `handler_routing.py` imports every handler, so the one test that needs it
reads it with `ast` rather than importing it. That is load-bearing for offline
runnability, not a stylistic preference, and
`tests/test_client_errors.py::test_client_import_is_workstation_safe` is what
keeps the two parser modules ldb-free so this file can keep collecting.
"""

import ast
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

import pytest
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from samba_adws._write_request import (
    CREATE_ACTION,
    DELETE_ACTION,
    PUT_ACTION,
    SET_PASSWORD_ACTION,
    Placement,
    build_create_request,
    build_delete_request,
    build_modify_request,
    build_rename_request,
    build_set_password_request,
)
from samba_adws._write_wire import ACCOUNT_PATH, FACTORY_PATH
from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient

SERVER = "dc.example.test"
PORT = 9389
PARENT = "OU=Staff,OU=Paris,DC=example,DC=test"
ACCOUNT = "CN=jdoe," + PARENT
WSA = "{http://www.w3.org/2005/08/addressing}"
ROUTING = Path(__file__).resolve().parents[1] / "src" / "handlers" / "handler_routing.py"


# Returns the entries the server reads out of an AddRequest this client built.
def added(rdn: str = "CN=jdoe", parent: str = PARENT,
          **attributes: Any) -> List[Dict[str, Any]]:
    envelope, _ = build_create_request(SERVER, PORT, Placement(rdn, parent), attributes)
    return BodyParser(envelope).find_add_request() or []


# Returns the entries the server reads out of a ModifyRequest this client built.
def changed(envelope: str) -> List[Dict[str, Any]]:
    return BodyParser(envelope).find_modify_request() or []


# Returns one entry by name from what the server read, or fails the test.
def entry(entries: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    found = [item for item in entries if item["name"].lower() == name.lower()]
    assert found, "the server read no " + name + "; it read " + str(
        [item["name"] for item in entries])
    return found[0]


# Returns the text of one WS-Addressing header of a built envelope.
def addressed(envelope: str, tag: str = "To") -> str:
    return ET.fromstring(envelope).findtext(f".//{WSA}{tag}") or ""


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
    for action in (CREATE_ACTION, PUT_ACTION, DELETE_ACTION, SET_PASSWORD_ACTION):
        resolvable = action.lower() in known or action.rsplit("/", 1)[-1] in known
        assert resolvable, "nothing in handler_routing.py answers " + action


# The name and the parent arrive as the two fields the server composes a DN from.
def test_the_server_gets_the_two_halves_it_composes_a_name_from() -> None:
    entries = added()
    assert entry(entries, "relativeDistinguishedName")["values"] == ["CN=jdoe"]
    assert entry(entries, "container-hierarchy-parent")["values"] == [PARENT]


# A composed name is never sent: the server decides how a directory spells one.
def test_no_assembled_distinguished_name_is_sent() -> None:
    assert "distinguishedname" not in [item["name"].lower() for item in added()]


# An ordinary attribute reaches the server under the name it was given.
def test_an_attribute_reaches_the_server_named_as_it_was_given() -> None:
    entries = added(sAMAccountName=["jdoe"], displayName=["Jane Doe"])
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
def test_a_value_carrying_markup_survives_intact(awkward: str) -> None:
    assert entry(added(description=[awkward]), "description")["values"] == [awkward]


# A name carrying markup survives too, which is the half a test usually misses.
#
# `_write_body._qualified` escapes the attribute name as well as the value.
# Nothing else pins that, and an unescaped name is the same parse failure one
# element to the left.
def test_a_name_carrying_markup_survives_intact() -> None:
    entries = added(**{"weird&<name>": ["x"]})
    assert entry(entries, "weird&<name>")["values"] == ["x"]


# The awkward string survives every write path, not only the create body.
#
# `conftest.py` calls it the one string every write path is fed; this is that
# claim made true for the rename, the modify, the delete target and the secret.
def test_the_awkward_string_survives_every_write_path(awkward: str) -> None:
    modified, _ = build_modify_request(SERVER, PORT, ACCOUNT, {"info": (awkward,)})
    assert entry(changed(modified), "info")["values"] == [awkward]
    renamed, _ = build_rename_request(SERVER, PORT, ACCOUNT, Placement(f"CN={awkward}", ""))
    assert entry(changed(renamed), "relativeDistinguishedName")["values"] == [
        f"CN={awkward}"]
    deleted, _ = build_delete_request(SERVER, PORT, awkward)
    assert RequestContext.from_xml(deleted).object_reference == awkward
    secret, _ = build_set_password_request(SERVER, PORT, ACCOUNT, awkward)
    parser = BodyParser(secret)
    assert parser.text_of(parser.find_custom_body("SetPasswordRequest"),
                          "NewPassword") == awkward


# A modify is read as a replacement of the attributes it names.
#
# One exchange for several attributes: the server applies them as a single LDAP
# modify, where three calls would be three transactions that can half-apply.
def test_a_modify_is_read_as_a_replace_of_the_attributes_it_names() -> None:
    envelope, _ = build_modify_request(
        SERVER, PORT, ACCOUNT, {"sn": ("Doe",), "userAccountControl": ("512",)})
    read = [(c["name"], c["operation"], c["values"]) for c in changed(envelope)]
    assert read == [("sn", "replace", ["Doe"]),
                    ("userAccountControl", "replace", ["512"])]


# An empty value list is a clear on a modify and a refusal on a create.
#
# The two halves of the `allow_empty` split, pinned in both directions: without
# the second assertion an attribute named with nothing in it reaches the wire as
# a create the server cannot satisfy.
def test_an_empty_value_list_clears_on_modify_and_is_refused_on_create() -> None:
    envelope, _ = build_modify_request(SERVER, PORT, ACCOUNT, {"info": ()})
    assert [(c["name"], c["operation"], c["values"]) for c in changed(envelope)] == [
        ("info", "replace", [])]
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER, PORT).create("CN=jdoe", PARENT, {"info": []})
    assert raised.value.code == "InvalidArgument"


# Attributes that are not a mapping are refused before anything is built.
def test_a_non_mapping_attributes_argument_is_refused() -> None:
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER, PORT).create(
            "CN=jdoe", PARENT, [("sn", ["Doe"])])  # type: ignore[arg-type]
    assert raised.value.code == "InvalidArgument"


# A rename is a ModifyRequest, never an AddRequest.
#
# `ModifyHandler._read_entries` falls back to `find_add_request` when it finds
# no ModifyRequest, so an AddRequest here would still rename the object and the
# mistake would never surface. This is the assertion that would catch it.
def test_a_rename_is_a_modify_request_and_not_an_add_request() -> None:
    envelope, _ = build_rename_request(SERVER, PORT, ACCOUNT, Placement("CN=jane", ""))
    assert BodyParser(envelope).find_modify_request()
    assert BodyParser(envelope).find_add_request() is None


# A rename sends only the half that changed, so the server keeps the other.
#
# `ModifyHandler._apply_rename` falls back to the object's current relative name
# or its current parent for whichever key is absent. Sending an empty value
# instead of omitting the key would rename the object to nothing.
@pytest.mark.parametrize(
    "new_rdn,new_parent,expected",
    [("CN=jane", "", ["relativedistinguishedname"]),
     ("", "OU=Other,DC=example,DC=test", ["container-hierarchy-parent"]),
     ("CN=jane", "OU=Other,DC=example,DC=test",
      ["relativedistinguishedname", "container-hierarchy-parent"])],
)
def test_a_rename_sends_only_the_half_that_changed(
        new_rdn: str, new_parent: str, expected: List[str]) -> None:
    envelope, _ = build_rename_request(
        SERVER, PORT, ACCOUNT, Placement(new_rdn, new_parent))
    assert sorted(c["name"].lower() for c in changed(envelope)) == sorted(expected)


# A rename that changes nothing, or that names a blank half, is refused.
#
# Both halves blank: the server would find no rename keys, skip the rename and
# answer success, so a caller that meant to move something would be told it had.
#
# One blank half beside a real one is the case that hides: `build_rename_request`
# omits an absent half and sends a present one as given, so `new_rdn="   "` with
# a real parent would go out as a relative name of three spaces and come back as
# a server-side ModifyFailed instead of the client-side refusal this validator
# exists to give. The last two rows are that case, in both positions.
@pytest.mark.parametrize("new_rdn,new_parent", [
    ("", ""),
    ("  ", "  "),
    ("   ", "OU=Other,DC=example,DC=test"),
    ("CN=jane", "   "),
])
def test_a_rename_that_changes_nothing_or_names_a_blank_half_is_refused(
        new_rdn: str, new_parent: str) -> None:
    with pytest.raises(ADWSClientError) as raised:
        ADWSWriteClient(SERVER, PORT).rename(
            ACCOUNT, new_rdn=new_rdn, new_parent=new_parent)
    assert raised.value.code == "InvalidArgument"
    assert raised.value.target == ACCOUNT


# The password body is the element the server's SetPassword handler looks for.
def test_the_password_body_is_the_one_set_password_reads() -> None:
    envelope, _ = build_set_password_request(SERVER, PORT, ACCOUNT, "C0rrect-Horse")
    parser = BodyParser(envelope)
    body = parser.find_custom_body("SetPasswordRequest")
    assert body is not None
    assert parser.text_of(body, "AccountDN") == ACCOUNT
    assert parser.text_of(body, "NewPassword") == "C0rrect-Horse"


# Each action is addressed to the endpoint its WCF contract is published on.
#
# The reason is MS-ADDM endpoint fidelity against a Windows DC. It is not that
# this server refuses the wrong one: `HandlerRegistry.resolve` routes on
# `<a:Action>` alone and never reads `<a:To>`, and `_nettcp` negotiates the NMF
# Via as the Resource path regardless. `ResourceFactory` is the single address
# this server does read — `CreateHandler._success` rewrites it into the
# ResourceCreated EPR it replies with.
def test_each_action_is_addressed_to_its_published_endpoint() -> None:
    create, _ = build_create_request(SERVER, PORT, Placement("CN=jdoe", PARENT), {})
    password, _ = build_set_password_request(SERVER, PORT, ACCOUNT, "s")
    assert addressed(create).endswith(FACTORY_PATH)
    assert addressed(password).endswith(ACCOUNT_PATH)
    for built in (build_modify_request(SERVER, PORT, ACCOUNT, {"sn": ("Doe",)}),
                  build_delete_request(SERVER, PORT, ACCOUNT),
                  build_rename_request(SERVER, PORT, ACCOUNT,
                                       Placement("CN=jane", ""))):
        assert addressed(built[0]).endswith("/Windows/Resource")


# A delete names its target where the delete handler reads one.
def test_a_delete_names_its_target_where_the_handler_reads_it() -> None:
    envelope, message_id = build_delete_request(SERVER, PORT, ACCOUNT)
    context = RequestContext.from_xml(envelope)
    assert context.object_reference == ACCOUNT
    assert context.message_id == message_id
    assert context.action == DELETE_ACTION


# A create names its parent, which is the fallback the server composes with.
#
# `CreateHandler._resolve_dn` takes the parent from the body and falls back to
# the object reference when the body carries none. Sending it in both places
# costs one header and removes a way for a create to arrive unplaceable.
def test_a_create_names_its_parent_as_the_servers_fallback() -> None:
    envelope, _ = build_create_request(SERVER, PORT, Placement("CN=jdoe", PARENT), {})
    assert RequestContext.from_xml(envelope).object_reference == PARENT


# Two requests never carry the same MessageID.
#
# The correlation check is only worth having while the identifiers differ;
# repeating one would let a stale response satisfy it.
def test_each_request_is_correlated_by_its_own_identifier() -> None:
    made = {build_delete_request(SERVER, PORT, ACCOUNT)[1] for _ in range(20)}
    assert len(made) == 20


# An identity the client cannot use is refused before anything is built, and the
# refusal names the value it refused.
#
# `.target` is the field a caller keys on to learn which object a write failed
# for, and every other refusal on these five verbs sets it. This one did not:
# `validate_identity` raised with no target, `ADWSClient.get_by_dn` backfills one
# only for errors raised inside its own exchange, and the write verbs have no
# such wrapper at all — so this was the single write failure that named nothing.
@pytest.mark.parametrize("identity", ["", "   "])
@pytest.mark.parametrize(
    "verb", ["create", "modify", "delete", "rename", "set_password"])
def test_an_empty_identity_is_refused_before_the_wire(verb: str, identity: str) -> None:
    client = ADWSWriteClient(SERVER, PORT)
    calls = {
        "create": lambda: client.create(identity, PARENT, {"sn": ("Doe",)}),
        "modify": lambda: client.modify(identity, {"sn": ("Doe",)}),
        "delete": lambda: client.delete(identity),
        "rename": lambda: client.rename(identity, new_rdn="CN=jane"),
        "set_password": lambda: client.set_password(identity, "C0rrect-Horse"),
    }
    with pytest.raises(ADWSClientError) as raised:
        calls[verb]()
    assert raised.value.code == "InvalidArgument"
    assert raised.value.target == identity
