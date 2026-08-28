"""The directory search one Enumerate request asks for."""
from dataclasses import dataclass
from typing import List

from classes.parsing.context import RequestContext
from classes.parsing.filter_parser import FilterParser
from classes.serialization.constructed_attrs import ConstructedAttrs

BASE_SCOPE = "Base"
DEFAULT_SCOPE = "Subtree"


# Carries the values one directory search needs, resolved once so that the
# handler never has to reconcile the scope and the projection twice. The scope
# stays the word the client sent: turning it into an ldb constant belongs to
# the handler that talks to LDB, and leaving it out keeps this module free of
# the directory bindings, so the projection rule is testable off a DC.
@dataclass(frozen=True)
class EnumerateQuery:
    base_dn: str
    search_filter: str
    scope_name: str
    attributes: List[str]


# Normalises the client filter (e.g. wraps bare NOT operands); raw on failure.
def normalize_filter(raw: str) -> str:
    try:
        return FilterParser().parse(raw)
    except ValueError:
        return raw


# Resolves a request into the search it describes, defaulting an absent scope
# to Subtree and projecting the selection onto whatever that scope can serve.
# Only the exact word 'Base' is a base search, which is also the only scope the
# ldb mapping in enumerate.py reads as SCOPE_BASE.
def build_query(context: RequestContext, base_dn: str) -> EnumerateQuery:
    scope_name = context.ldap_scope or DEFAULT_SCOPE
    attributes = ConstructedAttrs.for_scope(
        context.selection_attributes, scope_name == BASE_SCOPE
    )
    search_filter = normalize_filter(context.ldap_filter or "(objectClass=*)")
    return EnumerateQuery(base_dn, search_filter, scope_name, attributes)
