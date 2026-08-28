"""SOAP response validation for the supported Enumerate and Pull operations.

**A Pull answers with a batch and a way to continue, or with neither.** The end
of a sequence is `wsen:EndOfSequence`, an empty element, and its absence is what
says there is more. A client that inferred the end from an empty batch instead
would loop forever against a server that answers a short page before its last
one, and would stop early against one that answers an empty page in the middle.

**An object with no attributes is not a malformed response.** It is what a
projection asking for attributes that object does not carry produces, and losing
the whole page over it would be the client deciding that a legal answer is a
fault.

The structural class of each object is the last value of `objectClass`, which
the server guarantees is present: `EnumerateHandler` adds it to any projection
that omits it, precisely so a caller never has to read it off the element name.
"""

import xml.etree.ElementTree as ET
from typing import Mapping, Optional, Tuple

from samba_adws._envelope import check_action, parse_root, read_body
from samba_adws._search_request import ENUMERATE_RESPONSE_ACTION, PULL_RESPONSE_ACTION
from samba_adws._values import decode_object
from samba_adws.errors import ADWSClientError
from src.soap.namespaces import WSEN

Page = Tuple[Tuple[Mapping[str, object], ...], Optional[str]]


# Validates correlation and returns the opaque context an Enumerate opened.
def parse_enumerate_response(xml: str, expected_message_id: str, target: str) -> str:
    root = parse_root(xml, target)
    body = read_body(root, expected_message_id, target)
    check_action(root, ENUMERATE_RESPONSE_ACTION, target)
    context = body.findtext(f".//{{{WSEN}}}EnumerationContext")
    if not context or not context.strip():
        message = "Enumerate response carries no enumeration context"
        raise ADWSClientError(message, "MalformedResponse", target)
    return context


# Validates correlation and returns one batch with the context to continue from.
#
# The second element is None at the end of the sequence, and is what a caller
# loops on. It is opaque: this client never parses one and never builds one.
def parse_pull_response(xml: str, expected_message_id: str, target: str) -> Page:
    root = parse_root(xml, target)
    body = read_body(root, expected_message_id, target)
    check_action(root, PULL_RESPONSE_ACTION, target)
    response = body.find(f".//{{{WSEN}}}PullResponse")
    if response is None:
        raise ADWSClientError("Pull response has no PullResponse", "MalformedResponse", target)
    return _items(response), _continuation(response, target)


# Decodes every object in the batch, in the order the server sent them.
def _items(response: ET.Element) -> Tuple[Mapping[str, object], ...]:
    container = response.find(f"./{{{WSEN}}}Items")
    if container is None:
        return ()
    return tuple(decode_object(item) for item in container)


# Returns the next context, or None when the server said the sequence ended.
#
# Neither present is refused rather than guessed at. Treating it as the end
# would silently truncate a directory listing, and treating it as more would
# spin: the two failures are opposite and neither is detectable afterwards.
def _continuation(response: ET.Element, target: str) -> Optional[str]:
    if response.find(f"./{{{WSEN}}}EndOfSequence") is not None:
        return None
    context = response.findtext(f"./{{{WSEN}}}EnumerationContext")
    if context and context.strip():
        return context
    message = "Pull response says neither EndOfSequence nor a context to continue from"
    raise ADWSClientError(message, "MalformedResponse", target)
