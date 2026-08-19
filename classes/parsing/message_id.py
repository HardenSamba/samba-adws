"""
The MessageID of a request that could not be parsed
A fault carrying no RelatesTo is ignored by the client, so the identifier has
to be recoverable from text that is not a well formed document.
"""

import re
from typing import Optional

# How far into the request the scan reaches. MessageID is a header, so it comes
# early; the rest is a payload an unauthenticated peer chose and is not read.
SCAN_LIMIT = 8192

# The longest identifier lifted into a response header. A urn:uuid is 45
# characters; the cap is generous and still keeps a runaway value out.
MAX_LENGTH = 256

# A MessageID element under any namespace prefix, in text that need not parse.
_MESSAGE_ID = re.compile(r"<\s*(?:[\w.-]+:)?MessageID[^>]*>([^<]*)<")


# Recovers the MessageID from request text without requiring it to parse, so
# that a fault raised before parsing can still relate to its request.
def extract(xml: Optional[str]) -> str:
    if not xml:
        return ""
    found = _MESSAGE_ID.search(xml[:SCAN_LIMIT])
    if not found:
        return ""
    candidate = found.group(1).strip()
    return candidate if len(candidate) <= MAX_LENGTH else ""
