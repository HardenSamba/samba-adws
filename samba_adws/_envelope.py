"""SOAP envelope handling shared by every supported client operation.

Extracted from `_response`, which was the only reader until searching arrived.
Correlation, fault translation and envelope shape are the same three checks for
every operation, and the one that is easiest to get subtly wrong twice is
correlation: a client that accepts a response it did not ask for reads one
object's attributes as another's, and nothing about the result looks wrong.
"""

import xml.etree.ElementTree as ET
from typing import NoReturn, Optional

from src.soap.namespaces import DA, SOAP_ENV, WSA

from samba_adws.errors import ADWSClientError


# Parses SOAP XML and checks the expected envelope root.
def parse_root(xml: str, target: Optional[str]) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ADWSClientError("Malformed SOAP response", "MalformedResponse", target) from error
    if root.tag != f"{{{SOAP_ENV}}}Envelope":
        raise ADWSClientError("Response is not a SOAP 1.2 envelope", "MalformedResponse", target)
    return root


# Refuses a response that answers a different request than the one sent.
#
# Shared with the write path rather than copied into it: this is the check that
# is easiest to get subtly wrong twice, and a second copy is a second place for
# it to rot. `_write_response.parse_write_response` calls the same three lines.
def check_correlation(root: ET.Element, message_id: str, target: Optional[str]) -> None:
    relates_to = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}RelatesTo")
    if relates_to != message_id:
        raise ADWSClientError("ADWS response RelatesTo does not match", "CorrelationError", target)


# Returns the body of a correlated response, raising any fault it carries.
#
# Correlation first, then the fault, then the action. A fault that answers a
# different request is still the wrong answer, and reporting its reason would
# send the caller after a problem that belongs to somebody else's message.
#
# The non-empty body requirement is right for a Get and wrong for a write; see
# `_write_response`, which is why that path does not come through here.
def read_body(root: ET.Element, message_id: str, target: Optional[str]) -> ET.Element:
    check_correlation(root, message_id, target)
    body = root.find(f"./{{{SOAP_ENV}}}Body")
    if body is None or not list(body):
        raise ADWSClientError("ADWS response has no SOAP body", "MalformedResponse", target)
    fault = body.find(f"./{{{SOAP_ENV}}}Fault")
    if fault is not None:
        raise_fault(fault, target)
    return body


# Checks the action a response declares itself to be.
def check_action(root: ET.Element, expected: str, target: Optional[str]) -> None:
    action = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}Action")
    if action != expected:
        raise ADWSClientError("Unexpected ADWS response action", "MalformedResponse", target)


# Raises a structured client error from a SOAP 1.2 fault.
#
# The public code is the fault's own subcode, less its prefix. Most of this
# server's faults have none: `FaultBuilder.directory_error` sets no subcode and
# carries the discriminator in the Detail instead, as `da:ShortError` — which is
# where "CreateFailed", "ModifyFailed", "DeleteFailed", "InvalidRequest" and
# "ActionNotSupported" live. Reading it is the difference between telling a
# caller which of those happened and collapsing every write failure to
# "SOAPFault"; only SetPassword sets a subcode, so without this the write
# surface is where the loss lands.
#
# A ShortError of more than one word is not a code and is not used as one:
# `FaultBuilder` falls back to the whole message when a handler names no short
# error, and a sentence is not something a caller can branch on.
#
# A "not found" reason is normalized to ObjectNotFound whichever of the two
# carried it. Code selection is inlined here because it has no other caller, and
# this module is at the five-function ceiling CLAUDE.md 6.1 sets.
def raise_fault(fault: ET.Element, target: Optional[str]) -> NoReturn:
    subcode = fault.findtext(f"./{{{SOAP_ENV}}}Code/{{{SOAP_ENV}}}Subcode/{{{SOAP_ENV}}}Value")
    short = fault.findtext(f"./{{{SOAP_ENV}}}Detail/{{{DA}}}Fault/{{{DA}}}ShortError") or ""
    reason = fault.findtext(f"./{{{SOAP_ENV}}}Reason/{{{SOAP_ENV}}}Text")
    message = reason or "ADWS returned a SOAP fault"
    if "not found" in message.lower():
        code = "ObjectNotFound"
    elif subcode:
        code = subcode.rsplit(":", 1)[-1]
    elif len(short.split()) == 1:
        code = short.strip()
    else:
        code = "SOAPFault"
    raise ADWSClientError(message, code, target)
