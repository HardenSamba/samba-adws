"""Validation helpers for the public client boundary."""

import math
from typing import Sequence, Tuple

from samba_adws.errors import ADWSClientError


# Validates connection settings before any network activity occurs.
def validate_connection(server: str, port: int, timeout: float) -> None:
    if not isinstance(server, str) or not server.strip():
        target = server if isinstance(server, str) else None
        raise ADWSClientError("Server must be a non-empty name", "InvalidArgument", target)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ADWSClientError("Port must be between 1 and 65535", "InvalidArgument", server)
    valid_timeout = isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
    if not valid_timeout or timeout <= 0 or not math.isfinite(timeout):
        raise ADWSClientError("Timeout must be greater than zero", "InvalidArgument", server)


# Validates the distinguished name used as the object identity.
#
# The rejected value is carried as the error's target, the way `server` is
# above, so a caller reading `.target` sees what it passed rather than None.
# `ADWSClient.get_by_dn` backfills a target for everything raised inside its
# exchange, but this check runs before that block, and the write verbs have no
# such wrapper at all — without this they are the one failure that names nothing.
def validate_identity(identity: str) -> None:
    if not isinstance(identity, str) or not identity.strip():
        target = identity if isinstance(identity, str) else None
        raise ADWSClientError("Identity must be a non-empty distinguished name",
                              "InvalidArgument", target)


# Returns an immutable, validated property sequence.
def normalize_properties(properties: Sequence[str]) -> Tuple[str, ...]:
    if isinstance(properties, (str, bytes)):
        raise ADWSClientError("Properties must be a sequence of names", "InvalidArgument")
    try:
        result = tuple(properties)
    except TypeError as error:
        message = "Properties must be a sequence of names"
        raise ADWSClientError(message, "InvalidArgument") from error
    if any(not isinstance(name, str) or not name.strip() for name in result):
        raise ADWSClientError("Property names must be non-empty strings", "InvalidArgument")
    return result
