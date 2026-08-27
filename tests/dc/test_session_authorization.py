#!/usr/bin/env python3
"""The claim `#8` rests on, proved against a directory rather than argued.

Everything else about `#8` can be checked offline: that no request path can
reach a SYSTEM session, that the connection refuses a negotiation which produced
none, that `SambaDB` will not open without one. None of that is worth anything
if the premise underneath is false, and the premise is this:

**Handing `SamDB` a non-SYSTEM session makes Samba evaluate that principal's
ACLs.** If it did not, the whole change would be ceremony - the same writes
would still succeed, just with a different object passed in.

So this asks the directory. One unprivileged principal, one object it has no
right to modify, and the same modification as SYSTEM for contrast. The contrast
is the test: an environment where the write fails for an unrelated reason would
fail both ways, and that is not what is asserted.

Skipped wherever there is no directory. `tests/conftest.py` does the skipping.
"""
from __future__ import annotations

import logging
from typing import Any, Tuple

import pytest

pytestmark = pytest.mark.dc

# A password for a principal that exists only inside a test directory.
THROWAWAY = "Throwaway-Container-Pass2"
UNPRIVILEGED = "adws-test-lowly"


# The directory as SYSTEM, the same directory as an unprivileged principal, and
# an object that principal has no business modifying.
@pytest.fixture
def two_sessions(logger: logging.Logger) -> Tuple[Any, Any, str]:
    from samba.auth import (AUTH_SESSION_INFO_AUTHENTICATED,
                            AUTH_SESSION_INFO_DEFAULT_GROUPS,
                            AUTH_SESSION_INFO_SIMPLE_PRIVILEGES, user_session)
    from classes.directory import SambaDB
    from classes.directory.maintenance import local_session

    root = SambaDB(logger, session_info=local_session())
    base = str(root.db.domain_dn())
    if not root.db.search(base=base, expression=f"(sAMAccountName={UNPRIVILEGED})"):
        root.db.newuser(UNPRIVILEGED, THROWAWAY)
    who = root.db.search(base=base, expression=f"(sAMAccountName={UNPRIVILEGED})")[0].dn
    target = root.db.search(base=base, expression="(sAMAccountName=Administrator)")[0].dn
    flags = (AUTH_SESSION_INFO_DEFAULT_GROUPS | AUTH_SESSION_INFO_AUTHENTICATED
             | AUTH_SESSION_INFO_SIMPLE_PRIVILEGES)
    session = user_session(root.db, lp_ctx=None, dn=str(who), session_info_flags=flags)
    return root, SambaDB(logger, session_info=session), str(target)


# Attempts one modification and reports whether the directory allowed it.
def attempted(directory: Any, target: str, note: str) -> str:
    import ldb

    message = ldb.Message(ldb.Dn(directory.db, target))
    message["description"] = ldb.MessageElement(
        [note.encode()], ldb.FLAG_MOD_REPLACE, "description")
    try:
        directory.db.modify(message)
    except ldb.LdbError as error:
        return f"denied: {error.args[1]}"
    return "allowed"


# An authenticated principal can read the domain it belongs to.
def test_an_unprivileged_principal_can_still_read(
        two_sessions: Tuple[Any, Any, str]) -> None:
    import ldb

    _, lowly, _ = two_sessions
    found = lowly.db.search(base=str(lowly.db.domain_dn()), scope=ldb.SCOPE_BASE,
                            attrs=["objectClass"])
    assert found, "an authenticated principal that cannot read anything proves nothing"


# The same principal is refused a write it has no right to make.
def test_an_unprivileged_principal_is_refused_a_write(
        two_sessions: Tuple[Any, Any, str]) -> None:
    _, lowly, target = two_sessions
    assert attempted(lowly, target, "adws test").startswith("denied")


# SYSTEM is allowed the identical write, which is what makes the refusal mean
# something: the same message, the same object, one difference.
def test_the_same_write_is_allowed_as_system(
        two_sessions: Tuple[Any, Any, str]) -> None:
    root, _, target = two_sessions
    assert attempted(root, target, "adws test") == "allowed"


# A directory handed no session opens nothing, on a real directory too.
def test_no_session_opens_nothing(logger: logging.Logger) -> None:
    from classes.directory import SambaDB
    from classes.faults.exceptions import ADWSAccessDeniedException

    with pytest.raises(ADWSAccessDeniedException):
        _ = SambaDB(logger).db
