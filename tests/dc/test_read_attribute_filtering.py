#!/usr/bin/env python3
"""The read half of #8, which #17 says is missing. Skipped without a directory.

`tests/dc/test_session_authorization.py` proves the write half: handing `SamDB`
a non-SYSTEM session makes Samba evaluate that principal's ACLs on a write. The
read half does not hold, and this file is the executable statement of that.

**The test below is expected to fail, and that is asserted rather than
tolerated.** `xfail(strict=True)` means an unexpected pass is a failure: the day
somebody closes #17, this file stops the suite and says so, instead of quietly
agreeing with a fix nobody recorded. A comment saying "reads are not filtered"
rots the moment it stops being true; a strict xfail cannot.

Why it fails, from Samba's own source rather than from inference
(`source4/dsdb/samdb/ldb_modules/acl_read.c`, 4.22.10):

    if (!p || !p->enabled || am_system || !is_untrusted) {
            return ldb_next_request(module, req);
    }

`acl_read` is in the local module stack and is enabled — `p->enabled` is
`lpcfg_parm_bool(..., "acl", "search", true)`. It skips because `is_untrusted`
is false. That flag is set by `ldb_req_mark_untrusted()`, which is called from
`source4/ldap_server/ldap_backend.c` and from nowhere else, and which `pyldb.c`
does not expose. So no argument to `SamDB`, and no control a Python caller can
send, turns the filtering on. See #17 for what that leaves.
"""
from __future__ import annotations

import secrets
import subprocess
from typing import Any, Iterator, Tuple

import pytest

pytestmark = pytest.mark.dc

# The value the unprivileged principal must not be able to read. Generated per
# run so a leftover object from a crashed run cannot make a later run pass.
SECRET = "adws-i17-" + secrets.token_hex(8)


# A password for a principal that exists only for the length of one test.
def throwaway() -> str:
    return "Aa1!" + secrets.token_urlsafe(18)


# Returns one principal's distinguished name and its SID as text.
def principal(root: Any, name: str) -> Tuple[str, str]:
    from samba.dcerpc import security
    from samba.ndr import ndr_unpack

    found = root.db.search(base=str(root.db.domain_dn()),
                           expression=f"(sAMAccountName={name})",
                           attrs=["objectSid"])
    assert found, f"the fixture could not create {name}"
    sid = ndr_unpack(security.dom_sid, found[0]["objectSid"][0])
    return str(found[0].dn), str(sid)


# Two throwaway principals: one that may not read, and one it may not read from.
#
# The target carries a description, and an explicit deny on RIGHT_DS_READ_PROP
# for the other principal. That is the same shape #17 was reported with, and the
# same one `ldbsearch` over LDAP honours.
@pytest.fixture
def denied(logger: Any) -> Iterator[Tuple[Any, str]]:
    import ldb

    from classes.directory import SambaDB
    from classes.directory.maintenance import local_session
    from samba.auth import (AUTH_SESSION_INFO_AUTHENTICATED,
                            AUTH_SESSION_INFO_DEFAULT_GROUPS,
                            AUTH_SESSION_INFO_SIMPLE_PRIVILEGES, user_session)

    root = SambaDB(logger, session_info=local_session())
    stamp = secrets.token_hex(4)
    names = (f"adws-i17-lowly-{stamp}", f"adws-i17-target-{stamp}")
    try:
        for name in names:
            root.db.newuser(name, throwaway())
        who, sid = principal(root, names[0])
        target, _ = principal(root, names[1])

        message = ldb.Message(ldb.Dn(root.db, target))
        message["description"] = ldb.MessageElement(
            [SECRET.encode()], ldb.FLAG_MOD_REPLACE, "description")
        root.db.modify(message)
        subprocess.run(["samba-tool", "dsacl", "set", "--objectdn", target,
                        "--sddl", f"(D;;RP;;;{sid})"],
                       capture_output=True, text=True, check=True)

        flags = (AUTH_SESSION_INFO_DEFAULT_GROUPS | AUTH_SESSION_INFO_AUTHENTICATED
                 | AUTH_SESSION_INFO_SIMPLE_PRIVILEGES)
        session = user_session(root.db, lp_ctx=None, dn=who,
                               session_info_flags=flags)
        yield SambaDB(logger, session_info=session), target
    finally:
        for name in names:
            try:
                root.db.deleteuser(name)
            except Exception:
                pass


# The principal can still see the object, which is what makes the next test
# mean something: an environment where it saw nothing at all would pass the
# assertion below for a reason that has nothing to do with attribute filtering.
def test_the_denied_principal_can_still_see_the_object(
        denied: Tuple[Any, str]) -> None:
    import ldb

    lowly, target = denied
    found = lowly.db.search(base=target, scope=ldb.SCOPE_BASE, attrs=["objectClass"])
    assert found, "the principal cannot read the object at all; the test proves nothing"


# The attribute an explicit deny hides over LDAP is hidden from a local read.
#
# It is not. `acl_read` runs only for requests the LDAP frontend marked
# untrusted, so a directly opened SamDB returns the value. Remove the marker
# and close #17 in the same change; leaving the marker on a passing test is
# what strict=True exists to prevent.
@pytest.mark.xfail(strict=True, reason="samba-adws#17: local SamDB bypasses acl_read")
def test_a_denied_attribute_is_not_returned_by_a_local_read(
        denied: Tuple[Any, str]) -> None:
    import ldb

    lowly, target = denied
    found = lowly.db.search(base=target, scope=ldb.SCOPE_BASE, attrs=["description"])
    values = [str(v, "utf-8") for v in found[0].get("description", [])] if found else []
    assert SECRET not in values, (
        "a principal explicitly denied RIGHT_DS_READ_PROP read the attribute "
        "through a local SamDB; over LDAP the same principal sees nothing")
