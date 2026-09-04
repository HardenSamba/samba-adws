#!/usr/bin/env python3
"""The three exchanges against a real directory. Skipped without one.

`tests/test_accounts.py` proves the order and what each exchange carries.
Neither of the two things that matter most can be proved offline: that the
directory actually ends up with a usable account, and that when the sequence
stops after the create, what the directory is left holding is disabled. The
second is the security property `#43` names.

**The sequence is driven through the handlers, not over the network.** Every
request is built by the client and handed to the handler that would answer it,
which is the same path `tests/dc/test_write_verbs.py` takes; the transport is
the one layer left out.

**The refusal is scripted; the object it leaves behind is not.** The first
version of the property test asked the directory to refuse the password "a",
and the directory accepted it: this lab domain runs with complexity off and a
minimum length of one. A test that depends on a policy it does not control
proves nothing on a domain with a different one. So the create goes to the real
handler, the password exchange is answered with the fault the real handler
would build, and the assertion is about what the directory now holds — which
is the claim, and which no script can fake. A second test uses the domain's own
policy where that policy can refuse anything, and says so when it cannot.

Every import of `classes` or `ldb` is inside a function: the `dc` marker skips
at run time, after collection has already imported this module.
"""
from __future__ import annotations

import secrets
import xml.etree.ElementTree as ET
from typing import Any, Optional, Tuple

import pytest
from samba_adws import Account, AccountLeftDisabled, Placement
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._write_request import SET_PASSWORD_ACTION
from samba_adws.accounts import CREATED, ENABLED, USABLE, create_usable_account
from samba_adws.write_client import ADWSWriteClient

from tests.test_write_client import message_id_of, password_fault

pytestmark = pytest.mark.dc

SERVER = "dc.example.test"
WSA = "{http://www.w3.org/2005/08/addressing}"
DISABLED_BIT = 0x0002
# [MS-ADTS] 6.1.1.1.4: the pwdProperties bit that turns complexity on.
DOMAIN_PASSWORD_COMPLEX = 0x0001
# Satisfies a default Samba complexity policy.
GOOD = "Tr0ub4dor&<3>-" + secrets.token_hex(4)


# A transport that answers each request with the handler that would answer it,
# except the one action it is told to refuse, which gets the handler's fault.
#
# The client thinks it talked to a server; it talked to `HandlerRegistry`, which
# is what the server's dispatcher would have called, with the same bytes.
class HandlerTransport:
    def __init__(self, registry: Any, refuse: Optional[str] = None) -> None:
        self.registry = registry
        self.refuse = refuse

    def exchange(self, payload: bytes) -> bytes:
        from classes.parsing.context import RequestContext

        envelope = decode_xml(payload)
        action = ET.fromstring(envelope).findtext(f".//{WSA}Action")
        if action == self.refuse:
            return encode_xml(password_fault("refused by the test")(message_id_of(payload)))
        handler = self.registry.resolve(action)
        assert handler is not None, f"no handler resolves {action}"
        return encode_xml(str(handler.handle(RequestContext.from_xml(envelope))))

    def close(self) -> None:
        return None


# The userAccountControl the directory holds for one object, or None if absent.
def control_of(db: Any, dn: str) -> Optional[int]:
    import ldb

    found = db.search(base=dn, scope=ldb.SCOPE_BASE, attrs=["userAccountControl"])
    if not found or "userAccountControl" not in found[0]:
        return None
    return int(str(found[0]["userAccountControl"][0], "utf-8"))


# A password this domain's own policy will refuse, or None if it refuses none.
#
# Complexity on: a lone lowercase letter fails it. Otherwise a minimum length
# above one: a lone letter is too short. Otherwise the policy accepts anything
# the client lets through, and there is nothing a real refusal can be built on.
def refused_by_policy(db: Any) -> Optional[str]:
    import ldb

    found = db.search(base=str(db.domain_dn()), scope=ldb.SCOPE_BASE,
                      attrs=["minPwdLength", "pwdProperties"])
    properties = int(str(found[0].get("pwdProperties", [b"0"])[0], "utf-8"))
    minimum = int(str(found[0].get("minPwdLength", [b"0"])[0], "utf-8"))
    if properties & DOMAIN_PASSWORD_COMPLEX or minimum > 1:
        return "a"
    return None


# The directory as SYSTEM and the container new accounts go under.
@pytest.fixture
def directory() -> Tuple[Any, str]:
    from samba.auth import system_session
    from samba.param import LoadParm
    from samba.samdb import SamDB

    lp = LoadParm()
    lp.load_default()
    db = SamDB(session_info=system_session(), lp=lp)
    return db, f"CN=Users,{db.domain_dn()}"


# A client whose exchanges reach the handlers; `refuse` names one to fault.
def driven(registry: Any, monkeypatch: pytest.MonkeyPatch,
           refuse: Optional[str] = None) -> ADWSWriteClient:
    import samba_adws.client as client_module

    monkeypatch.setattr(client_module, "open_transport",
                        lambda server, port, timeout: HandlerTransport(registry, refuse))
    return ADWSWriteClient(SERVER)


# A fresh placement under Users, and its distinguished name for the clean-up.
def fresh(parent: str) -> Tuple[Placement, str]:
    name = "adws-i43-" + secrets.token_hex(5)
    return Placement(f"CN={name}", parent), f"CN={name},{parent}"


# Removes the object a test created, whether or not the sequence finished.
def remove(db: Any, dn: str) -> None:
    import ldb

    try:
        db.delete(ldb.Dn(db, dn))
    except ldb.LdbError:
        pass


# Runs the sequence for one fresh account; the name is the placement's own.
def attempted(client: ADWSWriteClient, placement: Placement, password: str) -> Account:
    return create_usable_account(
        client, placement,
        {"objectClass": ("user",), "sAMAccountName": (placement.rdn[3:],)}, password)


# A good password ends with a usable account: enabled, and only that.
def test_a_usable_account_is_left_enabled(
        registry: Any, monkeypatch: pytest.MonkeyPatch,
        directory: Tuple[Any, str]) -> None:
    db, parent = directory
    placement, dn = fresh(parent)
    try:
        account = attempted(driven(registry, monkeypatch), placement, GOOD)
        assert account.reached == USABLE
        assert account.dn == dn
        assert control_of(db, dn) == ENABLED
    finally:
        remove(db, dn)


# A refused password leaves a disabled account in the directory, and says so.
#
# The property this module exists for, asked of the directory. The create is
# the real handler's; the password exchange is refused; the object that remains
# is read back, and it must be disabled. The enable was never sent, which the
# offline suite proves; this proves what that means on disk.
def test_a_refused_password_leaves_a_disabled_account(
        registry: Any, monkeypatch: pytest.MonkeyPatch,
        directory: Tuple[Any, str]) -> None:
    db, parent = directory
    placement, dn = fresh(parent)
    try:
        client = driven(registry, monkeypatch, refuse=SET_PASSWORD_ACTION)
        with pytest.raises(AccountLeftDisabled) as raised:
            attempted(client, placement, GOOD)
        left = raised.value.account
        assert left.reached == CREATED
        assert left.dn == dn
        control = control_of(db, dn)
        assert control is not None, "the account the error names is not there"
        assert control & DISABLED_BIT == DISABLED_BIT
    finally:
        remove(db, dn)


# The same property with a refusal from the domain's own password policy.
#
# Where the policy can refuse a password, the directory does the refusing and
# nothing is scripted. Where it cannot — complexity off, minimum length of one,
# which is this lab — the test says so rather than passing on a premise that
# does not hold here.
def test_the_domain_policy_refusing_a_password_leaves_it_disabled(
        registry: Any, monkeypatch: pytest.MonkeyPatch,
        directory: Tuple[Any, str]) -> None:
    db, parent = directory
    weak = refused_by_policy(db)
    if weak is None:
        pytest.skip("this domain's password policy accepts any non-empty password")
    placement, dn = fresh(parent)
    try:
        with pytest.raises(AccountLeftDisabled) as raised:
            attempted(driven(registry, monkeypatch), placement, weak)
        assert raised.value.account.reached == CREATED
        control = control_of(db, dn)
        assert control is not None and control & DISABLED_BIT == DISABLED_BIT
    finally:
        remove(db, dn)
