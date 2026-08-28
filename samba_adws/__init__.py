"""Supported Linux client API for Samba Active Directory Web Services."""

# The version `MODULE.yaml` declares. Held here as well because `status`
# reports it and a probe cannot read the manifest; `tests/test_cli.py` holds
# the two together, so one cannot drift from the other quietly.
__version__ = "1.0.0"

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
    "__version__",
)
