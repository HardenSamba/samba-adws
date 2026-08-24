"""Validation for the supported search boundary.

Everything here is checked before a socket is opened, for the same reason
`_validation` checks a connection before one: a caller that mistyped a scope
should learn it from a message naming the three that exist, not from a fault
that travelled to a domain controller first.

**The scope words are the server's own.** `Base`, `OneLevel` and `Subtree` are
what `EnumerateHandler` maps onto `ldb.SCOPE_*`; anything else it does not
recognise falls through to `Subtree`, which is the widest of the three. A
caller who asked for one level and silently searched a whole domain is the one
mistake worth refusing here rather than passing on.
"""

from dataclasses import dataclass
from typing import Sequence, Tuple

from samba_adws._validation import normalize_properties
from samba_adws.errors import ADWSClientError

# The three the server maps onto ldb, spelled the way it spells them.
SCOPES: Tuple[str, ...] = ("Base", "OneLevel", "Subtree")

# What one Pull may ask for at most.
#
# `EnumerationRegistry.MAX_RESULTS_PER_CONTEXT` is 50000 and is a cap on the
# whole enumeration, not on one batch. This is a cap on the batch, and it is
# smaller on purpose: the point of paging is that a caller can show a screen
# before the domain has finished arriving.
MAX_PAGE_SIZE = 1000

# What a caller gets when it does not choose, matching the server's own default
# in `PullHandler` so an unset page size means the same thing on both sides.
DEFAULT_PAGE_SIZE = 100


# One search, validated. What `build_enumerate_request` is given.
@dataclass(frozen=True)
class SearchQuery:
    base: str
    scope: str
    ldap_filter: str
    properties: Tuple[str, ...]


# Validates one search and returns it, before anything reaches the network.
def search_query(
    base: str,
    scope: str = "OneLevel",
    ldap_filter: str = "(objectClass=*)",
    properties: Sequence[str] = (),
) -> SearchQuery:
    _require_text(base, "Search base must be a non-empty distinguished name")
    _require_text(ldap_filter, "Search filter must be a non-empty LDAP filter")
    if scope not in SCOPES:
        known = ", ".join(SCOPES)
        raise ADWSClientError(f"Scope must be one of {known}", "InvalidArgument", base)
    return SearchQuery(base, scope, ldap_filter, normalize_properties(properties))


# Validates one batch size, refusing the values that mean nothing.
#
# Zero is refused rather than treated as "no limit": a caller that computed a
# page size and got zero has a bug, and answering it with the whole domain is
# the least useful thing to do about that.
def page_size(count: int) -> int:
    if not isinstance(count, int) or isinstance(count, bool):
        raise ADWSClientError("Page size must be an integer", "InvalidArgument")
    if not 1 <= count <= MAX_PAGE_SIZE:
        message = f"Page size must be between 1 and {MAX_PAGE_SIZE}"
        raise ADWSClientError(message, "InvalidArgument")
    return count


# Validates the opaque cursor a caller hands back from a previous answer.
def enumeration_context(context: str) -> str:
    _require_text(context, "Enumeration context must be a non-empty string")
    return context


# Refuses a value that is not a non-empty string.
def _require_text(value: str, message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ADWSClientError(message, "InvalidArgument")
