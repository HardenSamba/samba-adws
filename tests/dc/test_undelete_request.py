#!/usr/bin/env python3
"""Restore-ADObject and the Administrative Center's Restore, against a directory.

The console restores a deleted object with a WS-Transfer Put that removes
isDeleted, and names the new place either with the synthetic
relativeDistinguishedName / container-hierarchy-parent attributes or with
distinguishedName; the plain Restore names none and goes back to the last
known parent. A directory takes the whole undelete as one modify: isDeleted
removed and distinguishedName replaced ([MS-ADTS] 3.1.1.5.3.7.2). A rename of
the deleted object first, as an ordinary Put does, is refused. This pins
UndeleteRequest on a domain provisioned for the test, so it needs the Samba
bindings but not a running controller. Every import is inside a function, for
the reason test_member_write_flags.py gives.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from typing import Any, Dict, Iterator, List

import pytest

pytestmark = pytest.mark.dc

REALM = "undelete.samba.example.com"


# A domain in a temporary directory, opened as the system account.
@pytest.fixture(scope="module")
def samdb() -> Iterator[Any]:
    from samba.auth import system_session
    from samba.provision import provision
    from samba.samdb import SamDB

    tempdir = tempfile.mkdtemp(prefix="adws-undelete")
    result = provision(logging.getLogger("tests"), system_session(),
                       targetdir=tempdir, realm=REALM, domain="UNDELETE",
                       hostname="undc", use_ntvfs=True, dns_backend="NONE",
                       serverrole="active directory domain controller")
    yield SamDB(url=result.lp.samdb_url(), lp=result.lp,
                session_info=system_session(result.lp))
    shutil.rmtree(tempdir, ignore_errors=True)


# Adds an OU and a user in it, deletes the user and returns (OU DN, deleted DN).
def deleted_user(samdb: Any, name: str) -> tuple[str, str]:
    ou = f"OU={name}-ou,{samdb.get_default_basedn()}"
    samdb.add({"dn": ou, "objectClass": "organizationalUnit"})
    samdb.add({"dn": f"CN={name},{ou}", "objectClass": "user",
               "sAMAccountName": name, "description": "kept"})
    samdb.delete(f"CN={name},{ou}")
    found = samdb.search(base=f"CN=Deleted Objects,{samdb.get_default_basedn()}",
                         expression=f"(sAMAccountName={name})",
                         controls=["show_deleted:1", "show_recycled:1"])
    assert len(found) == 1
    return ou, str(found[0].dn)


# Restores the deleted object as the Put carrying those changes would.
def restore(samdb: Any, dn: str, changes: List[Dict[str, Any]]) -> str:
    from classes.directory.undelete_request import UndeleteRequest

    entries = [{"name": "isDeleted", "operation": "delete", "values": []}] + changes
    assert UndeleteRequest.is_undelete(entries)
    restored: str = UndeleteRequest(samdb, ["sd_flags:1:0"]).restore(dn, entries)
    return restored


# Only an isDeleted removal is an undelete: a plain modify is left alone.
def test_only_an_isdeleted_removal_is_an_undelete() -> None:
    from classes.directory.undelete_request import UndeleteRequest

    assert not UndeleteRequest.is_undelete(
        [{"name": "description", "operation": "replace", "values": ["x"]}])
    assert not UndeleteRequest.is_undelete(
        [{"name": "isDeleted", "operation": "replace", "values": ["TRUE"]}])


# The plain Restore names no place: the object goes back where it was.
def test_restore_to_the_last_known_parent(samdb: Any) -> None:
    ou, deleted = deleted_user(samdb, "undel1")
    assert restore(samdb, deleted, []) == f"CN=undel1,{ou}"
    assert len(samdb.search(base=f"CN=undel1,{ou}", scope=0)) == 1


# Restore To: the new RDN and parent are the synthetic rename attributes.
def test_restore_with_the_rename_attributes(samdb: Any) -> None:
    ou, deleted = deleted_user(samdb, "undel2")
    target = f"CN=undel2-new,{samdb.get_default_basedn()}"
    changes = [
        {"name": "relativeDistinguishedName", "operation": "replace",
         "values": ["CN=undel2-new"]},
        {"name": "container-hierarchy-parent", "operation": "replace",
         "values": [str(samdb.get_default_basedn())]},
    ]
    assert restore(samdb, deleted, changes) == target
    assert len(samdb.search(base=target, scope=0)) == 1


# Restore To through distinguishedName, with another attribute changed at once.
def test_restore_with_the_distinguished_name(samdb: Any) -> None:
    ou, deleted = deleted_user(samdb, "undel3")
    target = f"CN=undel3,{ou}"
    changes = [
        {"name": "distinguishedName", "operation": "replace", "values": [target]},
        {"name": "description", "operation": "replace", "values": ["restored"]},
    ]
    assert restore(samdb, deleted, changes) == target
    found = samdb.search(base=target, scope=0, attrs=["description"])
    assert str(found[0]["description"]) == "restored"


# An object that is not deleted cannot be restored.
def test_restoring_a_live_object_fails(samdb: Any) -> None:
    from classes.faults.exceptions import ADWSDataException

    ou, deleted = deleted_user(samdb, "undel4")
    restored = restore(samdb, deleted, [])
    with pytest.raises(ADWSDataException):
        restore(samdb, restored, [])
