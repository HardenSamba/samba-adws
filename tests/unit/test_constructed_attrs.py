#!/usr/bin/env python3
"""ConstructedAttrs: which attributes a search of a given scope may ask for.

A real directory refuses `tokenGroups` outside a BASE search rather than
omitting it, and fails the whole query with "Indexed and full searches both
failed!" — so the projection has to depend on the scope. These cases run
without a directory: the module imports nothing but `typing`.
"""
from __future__ import annotations

from classes.serialization.constructed_attrs import (
    BASE_ONLY_ATTRIBUTES,
    CONSTRUCTED_ATTRIBUTES,
    ConstructedAttrs,
)


# A BASE search keeps the projection it has always had, token groups included.
def test_a_base_projection_still_asks_for_every_constructed_attribute() -> None:
    """classes/handlers/get.py is a BASE search and must keep working."""
    expanded = ConstructedAttrs.expand(None)
    assert expanded == ["*"] + list(CONSTRUCTED_ATTRIBUTES)
    projected = ConstructedAttrs.for_scope(None, is_base=True)
    assert projected == expanded + ["objectClass"]
    assert all(name in projected for name in BASE_ONLY_ATTRIBUTES)


# A wider search asks only for stored attributes plus the objectClass every
# rendered object needs.
def test_a_subtree_projection_asks_for_no_constructed_attribute() -> None:
    """This is the request that failed the whole search on a real DC."""
    projected = ConstructedAttrs.for_scope(None, is_base=False)
    assert projected == ["*", "objectClass"]
    assert ConstructedAttrs.for_scope([], is_base=False) == projected
    lowered = {name.lower() for name in projected}
    assert not lowered & {name.lower() for name in CONSTRUCTED_ATTRIBUTES}


# Naming a BASE-only attribute outside a BASE search drops that name, and
# keeps the rest of the selection intact.
def test_a_named_base_only_attribute_is_dropped_outside_base() -> None:
    """The object comes back without it, rather than the search failing."""
    assert ConstructedAttrs.for_scope(["tokenGroups", "cn"], is_base=False) == [
        "cn", "objectClass",
    ]
    assert ConstructedAttrs.for_scope(["TOKENGROUPSNOGCACCEPTABLE"], is_base=False) == [
        "objectClass",
    ]
    assert ConstructedAttrs.for_scope(
        ["tokenGroupsGlobalAndUniversal", "sn"], is_base=False
    ) == ["sn", "objectClass"]


# A constructed attribute any scope can serve survives when it is named.
def test_a_named_constructed_attribute_a_scope_can_serve_survives() -> None:
    """Only the three BASE-only names are refused, not all constructed ones."""
    assert ConstructedAttrs.for_scope(["canonicalName"], is_base=False) == [
        "canonicalName", "objectClass",
    ]
    assert ConstructedAttrs.is_constructed("canonicalName")


# No projection is ever empty, which ldb would read as "no attributes at all".
def test_a_projection_is_never_empty_and_never_repeats_object_class() -> None:
    """An empty attrs list is a different request, not a narrower one."""
    for is_base in (True, False):
        assert ConstructedAttrs.for_scope(None, is_base=is_base)
        assert ConstructedAttrs.for_scope([""], is_base=is_base)
    assert ConstructedAttrs.for_scope(["objectclass"], is_base=False) == ["objectclass"]
    assert ConstructedAttrs.for_scope(list(BASE_ONLY_ATTRIBUTES), is_base=False) == [
        "objectClass",
    ]
