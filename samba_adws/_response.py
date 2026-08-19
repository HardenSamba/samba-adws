"""SOAP response validation for the supported Get-by-DN operation."""

import xml.etree.ElementTree as ET
from typing import Mapping, NoReturn

from samba_adws._request import GET_RESPONSE_ACTION
from samba_adws._values import decode_body
from samba_adws.errors import ADWSClientError
from src.soap.namespaces import SOAP_ENV, WSA


# Validates correlation and returns the decoded Get response attributes.
def parse_get_response(xml: str, expected_message_id: str, target: str) -> Mapping[str, object]:
    root = _parse_root(xml, target)
    relates_to = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}RelatesTo")
    if relates_to != expected_message_id:
        raise ADWSClientError("ADWS response RelatesTo does not match", "CorrelationError", target)
    body = root.find(f"./{{{SOAP_ENV}}}Body")
    if body is None or not list(body):
        raise ADWSClientError("ADWS response has no SOAP body", "MalformedResponse", target)
    fault = body.find(f"./{{{SOAP_ENV}}}Fault")
    if fault is not None:
        _raise_fault(fault, target)
    action = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}Action")
    if action != GET_RESPONSE_ACTION:
        raise ADWSClientError("Unexpected ADWS response action", "MalformedResponse", target)
    return decode_body(body)


# Parses SOAP XML and checks the expected envelope root.
def _parse_root(xml: str, target: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ADWSClientError("Malformed SOAP response", "MalformedResponse", target) from error
    if root.tag != f"{{{SOAP_ENV}}}Envelope":
        raise ADWSClientError("Response is not a SOAP 1.2 envelope", "MalformedResponse", target)
    return root


# Raises a structured client error from a SOAP 1.2 fault.
def _raise_fault(fault: ET.Element, target: str) -> NoReturn:
    subcode = fault.findtext(f"./{{{SOAP_ENV}}}Code/{{{SOAP_ENV}}}Subcode/{{{SOAP_ENV}}}Value")
    reason = fault.findtext(f"./{{{SOAP_ENV}}}Reason/{{{SOAP_ENV}}}Text")
    message = reason or "ADWS returned a SOAP fault"
    code = _fault_code(subcode, message)
    raise ADWSClientError(message, code, target)


# Selects a stable public code from SOAP fault metadata.
def _fault_code(subcode: str | None, message: str) -> str:
    if "not found" in message.lower():
        return "ObjectNotFound"
    if subcode:
        return subcode.rsplit(":", 1)[-1]
    return "SOAPFault"
