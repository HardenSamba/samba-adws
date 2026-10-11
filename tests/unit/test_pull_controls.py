#!/usr/bin/env python3
"""pull_query: when the controls a Pull carries call for a fresh search."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from classes.enumeration.enumerate_query import EnumerateQuery
from classes.enumeration.enumeration_context import EnumerationContext
from classes.enumeration.pull_controls import pull_query

DELETED = "CN=Deleted Objects,DC=example,DC=com"


# Builds a cached enumeration whose search ran with the given controls.
def _context(controls: Optional[List[str]], served: int = 0) -> EnumerationContext:
    now = datetime.utcnow()
    query = EnumerateQuery(DELETED, "(objectClass=*)", "Subtree", ["name"], controls)
    return EnumerationContext(
        context_id="c", created_at=now, expires_at=now + timedelta(hours=1),
        base_dn=DELETED, search_filter="(objectClass=*)", result_index=served,
        query=query,
    )


# Get-ADObject -IncludeDeletedObjects puts show_deleted on the Pull only.
def test_show_deleted_on_the_first_pull_reruns_the_search_with_it() -> None:
    rerun = pull_query(_context(None), ["show_deleted:1", "show_deactivated_link:1"])
    assert rerun is not None
    assert rerun.controls == ["show_deleted:1", "show_deactivated_link:1"]
    assert (rerun.base_dn, rerun.scope_name) == (DELETED, "Subtree")


# Later Pulls repeat the same controls; the cached results already answer them.
def test_controls_already_searched_with_do_not_rerun() -> None:
    assert pull_query(_context(["show_deleted:1"]), ["show_deleted:1"]) is None


# Once a batch has been served, re-running would skip or repeat entries.
def test_no_rerun_after_the_first_batch() -> None:
    assert pull_query(_context(None, served=100), ["show_deleted:1"]) is None


# Only visibility controls trigger a rerun; the Enumerate's others are kept.
def test_other_pull_controls_are_ignored_and_enumerate_controls_kept() -> None:
    assert pull_query(_context(None), ["paged_results:1"]) is None
    rerun = pull_query(_context(["domain_scope:0"]), ["show_recycled:1"])
    assert rerun is not None and rerun.controls == ["domain_scope:0", "show_recycled:1"]
