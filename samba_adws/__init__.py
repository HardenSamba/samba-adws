"""Supported Linux client API for Samba Active Directory Web Services."""

from samba_adws.client import ADWSClient
from samba_adws.errors import ADWSClientError

__all__ = ("ADWSClient", "ADWSClientError")
