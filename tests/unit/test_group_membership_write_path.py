#!/usr/bin/env python3
"""How Add-ADGroupMember and Remove-ADGroupMember actually reach the directory.

Neither cmdlet has an operation of its own: IActiveDirectoryAccountManagement
declares six and none of them adds or removes a member. Both arrive as a
WS-Transfer Put whose body is a `<da:ModifyRequest>` changing `member`, which
TransferHandler routes to ModifyHandler and LdapAttrBuilder turns into an LDB
flag. This module pins the half that needs no directory: the parse, and the
routing that sends the Put to TransferHandler while a crafted `/Groups` action
now reaches nothing. tests/dc/test_member_write_flags.py pins the flag half.

The routing is read from the source with ast rather than imported, for the same
reason test_handler_coverage.py does it: importing the routing module pulls in
every handler and with them the directory bindings this suite must not require.
See HardenSamba/samba-adws#4.
"""
from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional

import pytest
from classes.parsing.body_parser import BodyParser

from tests.unit.test_handler_coverage import ROUTING

GROUP_DN = "CN=Demo Group,CN=Users,DC=samba,DC=local"
MEMBER_DN = "CN=userA,CN=Users,DC=samba,DC=local"
PUT_ACTION = "http://schemas.xmlsoap.org/ws/2004/09/transfer/Put"


# Builds the Put the ActiveDirectory module sends for a membership change.
def put_envelope(operation: str) -> str:
    return (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing" '
        'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:da="http://schemas.microsoft.com/2006/11/'
        'IdentityManagement/DirectoryAccess">'
        f'<s:Header><a:Action>{PUT_ACTION}</a:Action>'
        '<a:MessageID>urn:uuid:member-1</a:MessageID>'
        f'<ad:objectReferenceProperty>{GROUP_DN}</ad:objectReferenceProperty>'
        '</s:Header><s:Body>'
        f'<da:ModifyRequest><da:Change Operation="{operation}">'
        '<da:AttributeType>addata:member</da:AttributeType>'
        f'<da:AttributeValue><ad:value xsi:type="xsd:string">{MEMBER_DN}</ad:value>'
        '</da:AttributeValue></da:Change></da:ModifyRequest>'
        '</s:Body></s:Envelope>'
    )


# Replays HandlerRegistry.resolve against the routing source: the lowercased
# exact table names the key, and otherwise the case-sensitive last path segment
# does, but either way the key reaches a handler only if HANDLER_FACTORIES built
# one for it. Answers with that handler's class name, where resolve() answers
# with the handler instance itself.
def resolves_to(action: str) -> Optional[str]:
    tree = ast.parse(open(ROUTING, encoding="utf-8").read(), filename=ROUTING)
    assigned = {n.target.id: n.value for n in ast.walk(tree)
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    table, built = assigned["ACTION_HANDLER_KEYS"], assigned["HANDLER_FACTORIES"]
    assert isinstance(table, ast.Dict) and isinstance(built, ast.Tuple)
    pairs = zip(table.keys, table.values, strict=True)
    exact: Dict[str, str] = {str(k.value): str(v.value) for k, v in pairs
                             if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
    handlers: Dict[str, str] = {p.elts[0].value: p.elts[1].id  # type: ignore[attr-defined]
                                for p in built.elts}
    listed = exact.get(action.lower())
    return handlers.get(listed if listed is not None else action.rsplit("/", 1)[-1])


# A membership Put parses into exactly one change on member, carrying the
# operation the cmdlet chose, which LdapAttrBuilder maps to an LDB flag.
@pytest.mark.parametrize("operation", ["add", "delete"])
def test_a_membership_put_parses_into_one_member_change(operation: str) -> None:
    entries: Optional[List[Dict[str, Any]]] = BodyParser(
        put_envelope(operation)).find_modify_request()
    assert entries == [
        {"name": "member", "operation": operation, "values": [MEMBER_DN]}
    ]


# That Put is routed by the exact table to TransferHandler, so membership
# writes share the one tested write path rather than a group-specific action of
# the project's own. Naming the class, not the key, is what pins the path:
# repointing the "Put" registration elsewhere has to fail here.
def test_a_membership_put_routes_to_the_transfer_handler() -> None:
    assert resolves_to(PUT_ACTION) == "TransferHandler"


# resolve() falls back to the last path segment and the dispatcher puts no
# allowlist in front of it, so every registration key is reachable by a crafted
# action URI. Keeping "Groups" out of the routing is what keeps a crafted
# ".../Groups" request off a second, untested membership write path.
def test_a_crafted_groups_action_reaches_no_handler() -> None:
    assert resolves_to("http://tests.invalid/AccountManagement/Groups") is None
