"""
The security upgrade a client may ask for
[MC-NMF] 3.1.4.7: a supported upgrade earns an Upgrade Response Record; an
unsupported one MUST close the session and MAY carry a Fault Record first.
"""

from typing import Any

from src.nettcp import nmf

# The only upgrade this server implements. [MC-NMF] calls it the upgrade
# protocol name; this repository's own client sends exactly this string
# (src/nettcp/stream/nmf.py), and documentation/03-protocole.md records it.
EXPECTED_UPGRADE = "application/negotiate"

# [MC-NMF] 2.2.3.8 names this fault "The requested upgrade is not supported by
# the remote endpoint", under the framing fault namespace.
UPGRADE_INVALID = "http://schemas.microsoft.com/ws/2006/05/framing/faults/UpgradeInvalid"

# How much of a refused value reaches the log. Its length prefix is read before
# authentication, so the value is an unauthenticated peer's to choose.
LOG_EXCERPT = 64


# Tells whether the upgrade a record asks for is the one this server
# implements. The comparison is exact, with no trimming and no case folding:
# the .NET client sends the literal string and compares it ordinally.
def is_supported(record: Any) -> bool:
    return bool(getattr(record, "UpgradeProtocol", None) == EXPECTED_UPGRADE)


# Renders a refused value for one log line: bounded, quoted and escaped,
# because an unauthenticated peer chose it.
def describe(record: Any) -> str:
    requested = getattr(record, "UpgradeProtocol", None)
    if not isinstance(requested, str):
        return "<absent>"
    if len(requested) > LOG_EXCERPT:
        return f"{requested[:LOG_EXCERPT]!r}... ({len(requested)} chars)"
    return repr(requested)


# Builds the Fault Record that [MC-NMF] permits before the session is closed.
# The string is fixed, so nothing a peer sent is reflected back to it.
def fault_record() -> Any:
    encoded = UPGRADE_INVALID.encode("utf-8")
    return nmf.FaultRecord(FaultSize=len(encoded), Fault=UPGRADE_INVALID)
