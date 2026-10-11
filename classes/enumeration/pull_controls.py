"""The search a Pull asks for when it carries controls its Enumerate did not."""
from dataclasses import replace
from typing import List, Optional

from classes.enumeration.enumerate_query import EnumerateQuery
from classes.enumeration.enumeration_context import EnumerationContext
from classes.parsing.controls_parser import VISIBILITY_CONTROLS


# Returns the name an LDB control string starts with.
def control_name(control: str) -> str:
    return control.split(":", 1)[0]


# Keeps the deleted/recycled/deactivated-link visibility controls of a list.
def visibility_controls(controls: Optional[List[str]]) -> List[str]:
    return [c for c in controls or [] if control_name(c) in VISIBILITY_CONTROLS]


# Merges the controls already searched with, replacing any of the same name.
def merged_controls(searched: Optional[List[str]], added: List[str]) -> List[str]:
    names = {control_name(c) for c in added}
    return [c for c in searched or [] if control_name(c) not in names] + added


# Returns the query to re-run when a Pull adds visibility controls before the
# first batch was served, None when the cached results already answer it.
# [MS-WSPELD] carries enumeration controls on Pull, not on Enumerate.
def pull_query(
    enum_context: EnumerationContext, pull_controls: Optional[List[str]]
) -> Optional[EnumerateQuery]:
    query = enum_context.query
    added = visibility_controls(pull_controls)
    if not added or not isinstance(query, EnumerateQuery) or enum_context.result_index:
        return None
    if set(added) <= set(query.controls or []):
        return None
    return replace(query, controls=merged_controls(query.controls, added))
