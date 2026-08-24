"""Supported Linux client API for Samba Active Directory Web Services."""

from samba_adws._search_validation import SCOPES, SearchQuery, search_query
from samba_adws.client import ADWSClient
from samba_adws.errors import ADWSClientError
from samba_adws.search_client import ADWSSearchClient

__all__ = (
    "ADWSClient",
    "ADWSClientError",
    "ADWSSearchClient",
    "SCOPES",
    "SearchQuery",
    "search_query",
)
