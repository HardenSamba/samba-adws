#!/usr/bin/env python3
"""The LDB flag half of the membership write path. Skipped without bindings.

tests/unit/test_group_membership_write_path.py pins that Add-ADGroupMember and
Remove-ADGroupMember arrive as a WS-Transfer Put carrying a `<da:Change
Operation="add"|"delete">` on `member`. This pins what ModifyHandler then does
with it, which cannot be imported without python3-samba: `classes.directory`
imports `ldb` at module level, so every import here is deliberately inside a
function. The dc marker only skips at run time, after collection has already
imported the module. See HardenSamba/samba-adws#4.
"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.dc

GROUP_DN = "CN=Demo Group,CN=Users,DC=samba,DC=local"
MEMBER_DN = "CN=userA,CN=Users,DC=samba,DC=local"


# Builds the member element ModifyHandler._modify_attrs would send to LDB.
def member_element(operation: Any) -> Any:
    import ldb
    from classes.directory.ldap_attr_builder import LdapAttrBuilder

    entries = [{"name": "member", "operation": operation, "values": [MEMBER_DN]}]
    message = LdapAttrBuilder.build_message(
        ldb.Ldb(), GROUP_DN, entries, default_flag=ldb.FLAG_MOD_REPLACE)
    return message["member"]


# add edits the membership instead of overwriting it, and delete removes just
# the listed value: the two flags Add/Remove-ADGroupMember depend on.
@pytest.mark.parametrize(
    "operation,flag_name", [("add", "FLAG_MOD_ADD"), ("delete", "FLAG_MOD_DELETE")])
def test_a_membership_change_carries_the_flag_its_operation_names(
        operation: str, flag_name: str) -> None:
    import ldb

    element = member_element(operation)
    assert element.flags() == getattr(ldb, flag_name)
    assert list(element) == [MEMBER_DN.encode("utf-8")]


# A Change with no Operation falls back to the Put default and would replace
# the whole member list, which is why the cmdlets always send one.
def test_a_change_without_an_operation_falls_back_to_replace() -> None:
    import ldb

    assert member_element(None).flags() == ldb.FLAG_MOD_REPLACE
