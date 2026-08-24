"""Public searching ADWS client, extending the read-only ADWSClient.

`ADWSClient` can fetch one object whose distinguished name the caller already
knows. That is the wrong half for anything that draws a list: a console never
knows a distinguished name until it has listed something, so `get_by_dn` alone
leaves a Linux caller unable to find out what exists.

The server has done this since enumeration landed — `EnumerateHandler` runs the
query and caches it, `PullHandler` hands out batches — and nothing here reaches
past the supported boundary to get at it. These are the two SOAP messages, sent
the way a Windows client sends them.
"""

from typing import Iterator, Mapping, Optional

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._search_request import build_enumerate_request, build_pull_request
from samba_adws._search_response import Page, parse_enumerate_response, parse_pull_response
from samba_adws._search_validation import (
    DEFAULT_PAGE_SIZE,
    SearchQuery,
    enumeration_context,
    page_size,
)
from samba_adws.client import ADWSClient


# Adds the directory-listing verbs to the supported client surface.
class ADWSSearchClient(ADWSClient):

    # Opens a search and returns the opaque context to pull it from.
    #
    # Nothing is read yet. The server runs the query, caches what it matched and
    # hands back a handle with a lifetime; the objects arrive from `pull`.
    def open_search(self, query: SearchQuery) -> str:
        request, message_id = build_enumerate_request(self.server, self.port, query)
        response = self._exchange(encode_xml(request), query.base)
        return parse_enumerate_response(decode_xml(response), message_id, query.base)

    # Retrieves one batch, with the context to continue from or None at the end.
    #
    # The context is opaque: this client never parses one and never builds one.
    # A caller holding it across requests is holding the server's own cursor,
    # which is what makes paging a directory somebody else is writing to safe.
    # An offset would skip a row every time another administrator deletes one.
    def pull(self, context: str, count: int = DEFAULT_PAGE_SIZE) -> Page:
        checked = enumeration_context(context)
        wanted = page_size(count)
        request, message_id = build_pull_request(self.server, self.port, checked, wanted)
        response = self._exchange(encode_xml(request), checked)
        return parse_pull_response(decode_xml(response), message_id, checked)

    # Every object a search matches, one batch at a time.
    #
    # A generator rather than a list: a container holding forty thousand
    # accounts is the case paging exists for, and gathering them all would undo
    # it. A caller that wants one screenful calls `open_search` and `pull` and
    # keeps the context between requests.
    def search(
        self, query: SearchQuery, count: int = DEFAULT_PAGE_SIZE
    ) -> Iterator[Mapping[str, object]]:
        context: Optional[str] = self.open_search(query)
        while context is not None:
            objects, context = self.pull(context, count)
            yield from objects
