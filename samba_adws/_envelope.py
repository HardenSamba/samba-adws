"""SOAP envelope handling shared by every supported client operation.

Extracted from `_response`, which was the only reader until searching arrived.
Correlation, fault translation and envelope shape are the same three checks for
every operation, and the one that is easiest to get subtly wrong twice is
correlation: a client that accepts a response it did not ask for reads one
object's attributes as another's, and nothing about the result looks wrong.
"""

import xml.etree.ElementTree as ET
from typing import NoReturn, Optional

from samba_adws.errors import ADWSClientError
from src.soap.namespaces import SOAP_ENV, WSA


# Parses SOAP XML and checks the expected envelope root.
def parse_root(xml: str, target: Optional[str]) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ADWSClientError("Malformed SOAP response", "MalformedResponse", target) from error
    if root.tag != f"{{{SOAP_ENV}}}Envelope":
        raise ADWSClientError("Response is not a SOAP 1.2 envelope", "MalformedResponse", target)
    return root


# Returns the body of a correlated response, raising any fault it carries.
#
# Correlation first, then the fault, then the action. A fault that answers a
# different request is still the wrong answer, and reporting its reason would
# send the caller after a problem that belongs to somebody else's message.
def read_body(root: ET.Element, message_id: str, target: Optional[str]) -> ET.Element:
    relates_to = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}RelatesTo")
    if relates_to != message_id:
        raise ADWSClientError("ADWS response RelatesTo does not match", "CorrelationError", target)
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
def raise_fault(fault: ET.Element, target: Optional[str]) -> NoReturn:
    subcode = fault.findtext(f"./{{{SOAP_ENV}}}Code/{{{SOAP_ENV}}}Subcode/{{{SOAP_ENV}}}Value")
    reason = fault.findtext(f"./{{{SOAP_ENV}}}Reason/{{{SOAP_ENV}}}Text")
    message = reason or "ADWS returned a SOAP fault"
    raise ADWSClientError(message, fault_code(subcode, message), target)


# Selects a stable public code from SOAP fault metadata.
def fault_code(subcode: Optional[str], message: str) -> str:
    if "not found" in message.lower():
        return "ObjectNotFound"
    if subcode:
        return subcode.rsplit(":", 1)[-1]
    return "SOAPFault"
