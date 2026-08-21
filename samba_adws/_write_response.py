"""Response validation for the directory-changing operations."""

from src.soap.namespaces import SOAP_ENV, WSA

from samba_adws._response import _parse_root, _raise_fault
from samba_adws.errors import ADWSClientError


# Validates correlation and faults for a write; returns nothing on success.
def parse_write_response(xml: str, expected_message_id: str, target: str,
                         expected_action: str) -> None:
    root = _parse_root(xml, target)
    relates_to = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}RelatesTo")
    if relates_to != expected_message_id:
        raise ADWSClientError("ADWS response RelatesTo does not match",
                              "CorrelationError", target)
    body = root.find(f"./{{{SOAP_ENV}}}Body")
    fault = body.find(f"./{{{SOAP_ENV}}}Fault") if body is not None else None
    if fault is not None:
        _raise_fault(fault, target)
    action = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}Action")
    if action != expected_action:
        raise ADWSClientError("Unexpected ADWS response action",
                              "MalformedResponse", target)
