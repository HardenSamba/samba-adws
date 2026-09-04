"""The `search` subcommand: one page of objects, and how to ask for the next.

**One page per invocation, not the whole directory.** A command that ran a
subtree search to completion would hold a controller for as long as the domain
is large and hand its caller forty thousand objects at once. The caller asks
again with the cursor it was given, which is what the cursor is for.

**The cursor is the server's enumeration context, passed through unchanged.**
It is opaque here as it is in the client: nothing in this file parses one or
builds one. It expires — the server gives it an hour — and a caller that comes
back after that is told so rather than silently restarted, because silently
restarting a paged listing shows an operator the first page again and calls it
the second.

**A cursor does not outlive the connection that produced it.** The server forks
per connection and keeps its enumeration contexts in the child that answered
the Enumerate, so a cursor handed to a later invocation of this command names a
context that died with that process, and the server refuses it. Ask for the
page size you want with `--count`; a resumable cursor needs the server to hold
enumerations somewhere the next child can reach, which it does not yet do.

**Attributes are the directory's own.** `objectReferenceProperty`,
`distinguishedName`, `sAMAccountName` and the rest arrive as the server named
them and leave unchanged. A consumer that wanted different names would be
asking this command to hold its vocabulary, and there is more than one consumer.
"""

from typing import Any, Dict, Mapping, Optional, Sequence

from samba_adws._search_validation import SearchQuery, search_query
from samba_adws.search_client import ADWSSearchClient

# What a caller gets when it does not say. One screenful rather than a domain.
DEFAULT_COUNT = 50


# Builds the validated query from what the caller typed.
def query_from(base: str, scope: str, ldap_filter: str, properties: str) -> SearchQuery:
    wanted = tuple(name.strip() for name in properties.split(",") if name.strip())
    return search_query(base, scope, ldap_filter, wanted)


# One page, in the shape this command promises.
#
# `cursor` is empty at the end of the sequence, which is how a caller knows to
# stop: an empty `objects` is not the end, because a server may answer a short
# page or an empty one before its last.
def page(objects: Sequence[Mapping[str, object]], cursor: Optional[str]) -> Dict[str, Any]:
    return {"objects": [dict(entry) for entry in objects], "cursor": cursor or ""}


# Runs one page of a search against one server.
#
# The Enumerate and the Pull travel together on one connection, which is what
# `ADWSSearchClient.page` is for: the server keeps the context in the process
# that made it, and a second connection is a second process.
def run(client: ADWSSearchClient, query: SearchQuery, cursor: str, count: int) -> Dict[str, Any]:
    objects, following = client.page(query, cursor, count)
    return page(objects, following)
