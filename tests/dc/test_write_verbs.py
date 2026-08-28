#!/usr/bin/env python3
"""The five write verbs end to end against a real directory. Skipped without one.

`tests/test_write_request.py` proves the client's bytes are what the server's
parsers read, and `tests/test_write_client.py` proves what the client does with
an answer. Neither can prove the directory actually changed: `classes/handlers`
imports `ldb`, so the only place that question can be asked is on a provisioned
DC. This is that test, and it is here so the claim is re-runnable rather than a
sentence in a commit message.

**The client builds every request; nothing here writes XML.** The bytes handed
to each handler are the bytes `ADWSWriteClient` would have put on the wire, so a
change to a builder that the offline suite tolerates still has to survive a real
`ldb.add` here. The network is the only layer left out.

Every import of `classes` or `ldb` is inside a function: the `dc` marker skips at
run time, after collection has already imported this module.
"""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from typing import Any, List, Tuple

import pytest
from samba_adws._write_request import (
    Placement,
    build_create_request,
    build_delete_request,
    build_modify_request,
    build_rename_request,
    build_set_password_request,
)

pytestmark = pytest.mark.dc

SERVER = "dc.example.test"
PORT = 9389
# A password that satisfies a default Samba complexity policy.
PASSWORD = "Tr0ub4dor&<3>-" + uuid.uuid4().hex[:8]
WSA = "{http://www.w3.org/2005/08/addressing}"
SOAP = "{http://www.w3.org/2003/05/soap-envelope}"


# Returns a SamDB opened the way the server opens one, plus the domain DN.
def directory() -> Tuple[Any, str]:
    from samba.auth import system_session
    from samba.samdb import SamDB

    db = SamDB(session_info=system_session(), lp=_loadparm())
    return db, str(db.domain_dn())


# Returns the server's own loadparm, so this test reads the real smb.conf.
def _loadparm() -> Any:
    from samba.param import LoadParm

    lp = LoadParm()
    lp.load_default()
    return lp


# Drives one built request through the handler that answers its action.
#
# This is the server's own path: the registry resolves the action, the context
# is parsed from the client's bytes, and the handler talks to the directory.
def answered(registry: Any, built: Tuple[str, str]) -> ET.Element:
    from classes.parsing.context import RequestContext

    envelope, message_id = built
    action = ET.fromstring(envelope).findtext(f".//{WSA}Action")
    handler = registry.resolve(action)
    assert handler is not None, f"no handler resolves {action}"
    answer = ET.fromstring(str(handler.handle(RequestContext.from_xml(envelope))))
    assert answer.findtext(f".//{WSA}RelatesTo") == message_id
    return answer


# Fails the test with the fault's reason when an answer carries one.
def refuse_faults(answer: ET.Element, what: str) -> None:
    fault = answer.find(f".//{SOAP}Fault")
    reason = fault.findtext(f".//{SOAP}Text") if fault is not None else None
    assert fault is None, f"{what} was refused by the directory: {reason}"


# Returns the distinguished names one base search finds, or an empty list.
def found(db: Any, dn: str) -> List[Any]:
    import ldb

    try:
        return list(db.search(base=dn, scope=ldb.SCOPE_BASE, attrs=["objectGUID"]))
    except ldb.LdbError:
        return []


# create, set_password, modify, rename and delete, in that order, for real.
#
# The ordering is the one a caller must follow and the reason it matters: the
# account is created disabled, given a password, and only then enabled, so a
# failure at any step leaves a disabled object rather than an enabled one with
# no password. The rename then moves it and the delete removes it, which is also
# what keeps this test re-runnable rather than leaving litter behind.
def test_the_five_write_verbs_change_a_real_directory(registry: Any) -> None:
    db, domain = directory()
    parent = f"CN=Users,{domain}"
    name = "adws-write-" + uuid.uuid4().hex[:10]
    renamed = name + "-moved"
    dn = f"CN={name},{parent}"
    new_dn = f"CN={renamed},{parent}"
    try:
        created = answered(registry, build_create_request(
            SERVER, PORT, Placement(f"CN={name}", parent),
            {"objectClass": ("user",), "sAMAccountName": (name,),
             "userAccountControl": ("546",)}))
        refuse_faults(created, "the create")
        assert found(db, dn), "the create answered success but the object is not there"
        guid = created.findtext(".//{http://schemas.microsoft.com/2008/1"
                                "/ActiveDirectory}objectReferenceProperty")
        assert guid and guid != str(uuid.UUID(int=0)), (
            "the create reported no usable objectGUID")

        refuse_faults(answered(registry, build_set_password_request(
            SERVER, PORT, dn, PASSWORD)), "the password reset")
        refuse_faults(answered(registry, build_modify_request(
            SERVER, PORT, dn, {"userAccountControl": ("512",),
                               "description": ("créé & <société>",)})), "the modify")
        assert _attribute(db, dn, "description") == "créé & <société>"

        refuse_faults(answered(registry, build_rename_request(
            SERVER, PORT, dn, Placement(f"CN={renamed}", ""))), "the rename")
        assert found(db, new_dn) and not found(db, dn)
    finally:
        for leftover in (new_dn, dn):
            if found(db, leftover):
                answered(registry, build_delete_request(SERVER, PORT, leftover))
        assert not found(db, new_dn) and not found(db, dn)


# Returns one string attribute of one object, or None.
def _attribute(db: Any, dn: str, name: str) -> Any:
    import ldb

    result = db.search(base=dn, scope=ldb.SCOPE_BASE, attrs=[name])
    if not result or name not in result[0]:
        return None
    return str(result[0][name][0], "utf-8")
