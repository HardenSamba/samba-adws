#!/usr/bin/env python3
"""build_query: the scope a request resolves to is the scope it projects onto.

Issue #32 was not a wrong projection rule, it was a projection computed without
consulting the scope, so what has to be pinned is the wiring and not
`ConstructedAttrs` alone. These cases run without a directory because
`enumerate_query.py` never names an ldb constant: mapping the scope word onto
one belongs to `enumerate.py`, which is the module that talks to LDB. That is
also why it lives outside `classes/handlers/`, whose package import pulls the
directory bindings in.
"""
from __future__ import annotations

from typing import List, Optional

from classes.enumeration.enumerate_query import build_query
from classes.parsing.context import RequestContext

BASE_DN = "DC=example,DC=com"


# Builds the request an Enumerate arrives as, with only the fields the query
# resolution reads.
def _request(scope: Optional[str] = None,
             selection: Optional[List[str]] = None,
             ldap_filter: Optional[str] = None) -> RequestContext:
    return RequestContext(
        action="Enumerate", message_id="urn:uuid:32", ldap_scope=scope,
        selection_attributes=selection, ldap_filter=ldap_filter,
    )


# The request that failed on a real DC: no scope, no selection at all.
def test_a_bare_enumerate_is_a_subtree_search_that_asks_for_no_token_groups() -> None:
    """An absent scope is Subtree, and Subtree cannot serve tokenGroups."""
    query = build_query(_request(), BASE_DN)
    assert query.scope_name == "Subtree"
    assert query.attributes == ["*", "objectClass"]
    assert query.base_dn == BASE_DN
    assert query.search_filter == "(objectClass=*)"


# The seam itself: one selection, two scopes, two projections.
def test_the_resolved_scope_is_the_scope_the_projection_is_built_for() -> None:
    """A projection built for the wrong scope is the defect of issue #32."""
    selection = ["tokenGroups", "cn"]
    assert build_query(_request("Base", selection), BASE_DN).attributes == [
        "tokenGroups", "cn", "objectClass",
    ]
    assert build_query(_request("Subtree", selection), BASE_DN).attributes == [
        "cn", "objectClass",
    ]
    assert build_query(_request("OneLevel", selection), BASE_DN).attributes == [
        "cn", "objectClass",
    ]


# Only the exact word the ldb mapping reads as SCOPE_BASE is a base search.
def test_a_scope_word_the_ldb_mapping_does_not_know_is_projected_as_subtree() -> None:
    """Both sides fall back to Subtree, so they cannot disagree."""
    query = build_query(_request("onelevel", ["tokenGroups", "sn"]), BASE_DN)
    assert query.scope_name == "onelevel"
    assert query.attributes == ["sn", "objectClass"]


# The filter the search runs is the normalised one, not the raw request text.
def test_the_query_carries_the_normalised_filter() -> None:
    """A bare NOT operand is wrapped, and an unparseable filter is kept raw."""
    assert build_query(_request(ldap_filter="(!objectClass=user)"), BASE_DN).search_filter
    assert build_query(_request(ldap_filter="(cn=x)"), BASE_DN).search_filter == "(cn=x)"
    assert build_query(_request(ldap_filter="(("), BASE_DN).search_filter == "(("
