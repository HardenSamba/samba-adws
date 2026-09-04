"""Supported Linux client API for Samba Active Directory Web Services."""

# The version `MODULE.yaml` declares. Held here as well because `status`
# reports it and a probe cannot read the manifest; `tests/test_cli.py` holds
# the two together, so one cannot drift from the other quietly.
__version__ = "1.0.0"

from samba_adws._account import Account
from samba_adws._search_base import is_guid_base
from samba_adws._search_validation import SCOPES, SearchQuery, search_query
from samba_adws._write_request import Placement
from samba_adws.account_errors import AccountLeftDisabled
from samba_adws.accounts import create_usable_account
from samba_adws.client import ADWSClient
from samba_adws.errors import ADWSClientError
from samba_adws.membership_client import ADWSMembershipClient
from samba_adws.search_client import ADWSSearchClient
from samba_adws.write_client import ADWSWriteClient

__all__ = (
    "ADWSClient",
    "ADWSClientError",
    "ADWSMembershipClient",
    "ADWSSearchClient",
    "ADWSWriteClient",
    "Account",
    "AccountLeftDisabled",
    "Placement",
    "create_usable_account",
    "SCOPES",
    "SearchQuery",
    "is_guid_base",
    "search_query",
    "__version__",
)
