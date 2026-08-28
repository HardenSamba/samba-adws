#!/usr/bin/env python3
"""The claim `#8` rests on, proved against a directory rather than argued.

Everything else about `#8` can be checked offline: that no request path can
reach a SYSTEM session, that the connection refuses a negotiation which produced
none, that `SambaDB` will not open without one. None of that is worth anything
if the premise underneath is false, and the premise is this:

**Handing `SamDB` a non-SYSTEM session makes Samba evaluate that principal's
ACLs on a write.** If it did not, the whole change would be ceremony - the same
writes would still succeed, just with a different object passed in.

So this asks the directory. One unprivileged principal, one throwaway object it
has no right to modify, and the same modification as SYSTEM for contrast. The
contrast is the test: an environment where the write fails for an unrelated
reason would fail both ways, and that is not what is asserted.

Nothing here touches an object the directory already had. Both principals are
created by the fixture and deleted by it, so a failed run leaves the domain as
it found it. Reads are deliberately not asserted on: `acl_read` runs in Samba's
LDAP frontend and not on a directly opened local `SamDB`, so a read here runs as
the caller but is not attribute-filtered. That gap is
[#17](https://github.com/HardenSamba/samba-adws/issues/17), not this test.

Skipped wherever there is no directory. `tests/conftest.py` does the skipping.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Iterator, Sequence, Tuple

import pytest

pytestmark = pytest.mark.dc


# A password for a principal that exists only for the length of one test.
#
# Generated rather than written down, so that nothing in this repository is a
# credential and a leftover account from a crashed run is not a usable one.
def throwaway() -> str:
    return "Aa1!" + secrets.token_urlsafe(18)


# Creates one throwaway user as SYSTEM and returns its DN.
def made(root: Any, name: str) -> str:
    root.db.newuser(name, throwaway())
    base = str(root.db.domain_dn())
    found = root.db.search(base=base, expression=f"(sAMAccountName={name})")
    assert found, f"the fixture could not create {name}"
    return str(found[0].dn)


# Deletes what the fixture created, whatever the test did to it.
#
# Broad on purpose: teardown that raises would hide the assertion that failed,
# and a principal that was never created is not an error worth reporting here.
def removed(root: Any, names: Sequence[str]) -> None:
    for name in names:
        try:
            root.db.deleteuser(name)
        except Exception:
            pass


# The directory as SYSTEM, the same directory as an unprivileged principal, and
# a throwaway object that principal has no business modifying.
@pytest.fixture
def two_sessions(logger: logging.Logger) -> Iterator[Tuple[Any, Any, str]]:
    from samba.auth import (AUTH_SESSION_INFO_AUTHENTICATED,
                            AUTH_SESSION_INFO_DEFAULT_GROUPS,
                            AUTH_SESSION_INFO_SIMPLE_PRIVILEGES, user_session)

    from classes.directory import SambaDB
    from classes.directory.maintenance import local_session

    root = SambaDB(logger, session_info=local_session())
    stamp = secrets.token_hex(4)
    names = (f"adws-t-lowly-{stamp}", f"adws-t-target-{stamp}")
    flags = (AUTH_SESSION_INFO_DEFAULT_GROUPS | AUTH_SESSION_INFO_AUTHENTICATED
             | AUTH_SESSION_INFO_SIMPLE_PRIVILEGES)
    try:
        who = made(root, names[0])
        target = made(root, names[1])
        session = user_session(root.db, lp_ctx=None, dn=who, session_info_flags=flags)
        yield root, SambaDB(logger, session_info=session), target
    finally:
        removed(root, names)


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
    from classes.faults.exceptions import ADWSAuthenticationException

    with pytest.raises(ADWSAuthenticationException):
        _ = SambaDB(logger).db


# The session survives the plumbing between the connection and the directory.
#
# `identity.required` returning the caller is worth nothing if the object is
# dropped on the way down. The chain is dispatcher -> HandlerRegistry ->
# BaseHandler -> SambaDB, and every link takes `session_info` with a default of
# None, so a handler that forgot to pass it on would not fail here - it would
# fail much later, as a directory that refuses to open, on one action only.
def test_the_caller_session_reaches_every_handler(logger: logging.Logger) -> None:
    from classes.handlers.dispatcher import ADWSDispatcher

    caller = object()
    dispatcher = ADWSDispatcher(logger, session_info=caller)
    keys = dispatcher.registry.keys()
    assert keys, "a dispatcher with no handlers proves nothing"
    for key in keys:
        handler = dispatcher.registry.resolve(key)
        assert handler is not None, f"{key} no longer resolves"
        assert handler.db.session_info is caller, (
            f"{key} builds its directory without the session the caller "
            "authenticated as"
        )
