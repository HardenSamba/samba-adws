#!/usr/bin/env python3
"""Group membership end to end against a real directory. Skipped without one.

`tests/test_member_request.py` proves the server reads from this client what it
reads from `Add-ADGroupMember`; `tests/test_membership_client.py` proves what
the client does with an answer. Neither can prove a group actually changed, and
neither can say what the directory answers a redundant call with — which `#21`
asked for explicitly, because a console that races another administrator has
to know whether to render a refusal or nothing. Both questions are asked here.

**The client builds every request; nothing here writes XML.** The bytes handed
to the handler are the bytes `ADWSMembershipClient` would put on the wire. The
network is the only layer left out.

Every import of `classes` or `ldb` is inside a function: the `dc` marker skips
at run time, after collection has already imported this module.
"""
from __future__ import annotations

import secrets
import xml.etree.ElementTree as ET
from typing import Any, Iterator, List, Optional, Tuple

import pytest
from samba_adws._member_request import ADD, REMOVE, Membership, build_member_request

pytestmark = pytest.mark.dc

SERVER = "dc.example.test"
PORT = 9389
WSA = "{http://www.w3.org/2005/08/addressing}"
SOAP = "{http://www.w3.org/2003/05/soap-envelope}"
DA = "{http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess}"


# Drives one built request through the handler that answers its action.
def answered(registry: Any, built: Tuple[str, str]) -> ET.Element:
    from classes.parsing.context import RequestContext

    envelope, message_id = built
    action = ET.fromstring(envelope).findtext(f".//{WSA}Action")
    handler = registry.resolve(action)
    assert handler is not None, f"no handler resolves {action}"
    answer = ET.fromstring(str(handler.handle(RequestContext.from_xml(envelope))))
    assert answer.findtext(f".//{WSA}RelatesTo") == message_id
    return answer


# The fault's discriminator and reason, or None when the answer is a success.
def refusal(answer: ET.Element) -> Optional[Tuple[str, str]]:
    fault = answer.find(f".//{SOAP}Fault")
    if fault is None:
        return None
    short = fault.findtext(f".//{DA}ShortError") or ""
    reason = fault.findtext(f".//{SOAP}Text") or ""
    return short, reason


# The distinguished names a group currently lists as members.
def members(db: Any, group: str) -> List[str]:
    import ldb

    found = db.search(base=group, scope=ldb.SCOPE_BASE, attrs=["member"])
    return sorted(str(v, "utf-8") for v in found[0].get("member", [])) if found else []


# A throwaway group and a throwaway user, both created by SYSTEM and both
# deleted afterwards, whatever the test did to them.
@pytest.fixture
def pair() -> Iterator[Tuple[Any, str, str]]:
    import ldb
    from samba.auth import system_session
    from samba.param import LoadParm
    from samba.samdb import SamDB

    lp = LoadParm()
    lp.load_default()
    db = SamDB(session_info=system_session(), lp=lp)
    base = str(db.domain_dn())
    stamp = secrets.token_hex(4)
    names = (f"adws-i21-grp-{stamp}", f"adws-i21-usr-{stamp}")
    dns: List[str] = []
    try:
        db.newgroup(names[0])
        db.newuser(names[1], "Aa1!" + secrets.token_urlsafe(18))
        for name in names:
            dns.append(str(db.search(base=base, expression=f"(sAMAccountName={name})")[0].dn))
        yield db, dns[0], dns[1]
    finally:
        for dn in reversed(dns):
            try:
                db.delete(ldb.Dn(db, dn))
            except Exception:
                pass


# An add then a remove change the group the directory holds, not a copy of it.
def test_add_then_remove_changes_the_real_membership(
        registry: Any, pair: Tuple[Any, str, str]) -> None:
    db, group, user = pair
    edit = Membership(group, user)
    assert refusal(answered(registry, build_member_request(SERVER, PORT, edit, ADD))) is None
    assert members(db, group) == [user]
    assert refusal(answered(registry, build_member_request(SERVER, PORT, edit, REMOVE))) is None
    assert members(db, group) == []


# Adding a member the group already has is refused, and the refusal says so.
#
# This is the answer `#21` asked for. It is a refusal rather than a no-op: the
# directory answers LDB_ERR_ENTRY_ALREADY_EXISTS, and ModifyHandler carries it
# as ModifyFailed with the directory's own sentence as the reason.
def test_a_redundant_add_is_refused_as_modify_failed(
        registry: Any, pair: Tuple[Any, str, str]) -> None:
    _, group, user = pair
    edit = Membership(group, user)
    answered(registry, build_member_request(SERVER, PORT, edit, ADD))
    found = refusal(answered(registry, build_member_request(SERVER, PORT, edit, ADD)))
    assert found is not None, "a second add was accepted as if it changed something"
    short, reason = found
    assert short == "ModifyFailed"
    assert "already exists" in reason


# Removing a member the group never had is refused: LDB_ERR_NO_SUCH_ATTRIBUTE.
#
# Same code as a redundant add, different sentence. The directory has no value
# to delete and says so, and that sentence is the only thing that tells a caller
# which of the two happened.
def test_removing_a_member_it_never_had_is_refused_as_modify_failed(
        registry: Any, pair: Tuple[Any, str, str]) -> None:
    _, group, user = pair
    edit = Membership(group, user)
    found = refusal(answered(registry, build_member_request(SERVER, PORT, edit, REMOVE)))
    assert found is not None, "removing a non-member was accepted as if it changed something"
    short, reason = found
    assert short == "ModifyFailed"
    assert "No such attribute" in reason


# Removing a former member a second time is refused with a third sentence.
#
# The first removal leaves a linked-attribute tombstone rather than nothing, so
# the directory answers LDB_ERR_UNWILLING_TO_PERFORM, "already deleted", instead
# of "no such attribute". A console keying on one sentence would miss the other;
# both are pinned so the documentation can list both.
def test_removing_a_former_member_again_is_refused_as_modify_failed(
        registry: Any, pair: Tuple[Any, str, str]) -> None:
    _, group, user = pair
    edit = Membership(group, user)
    answered(registry, build_member_request(SERVER, PORT, edit, ADD))
    answered(registry, build_member_request(SERVER, PORT, edit, REMOVE))
    found = refusal(answered(registry, build_member_request(SERVER, PORT, edit, REMOVE)))
    assert found is not None, "a second removal was accepted as if it changed something"
    short, reason = found
    assert short == "ModifyFailed"
    assert "already deleted" in reason
