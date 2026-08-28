"""Response validation for the directory-changing operations."""

import xml.etree.ElementTree as ET
from typing import Optional

from samba_adws._envelope import check_action, parse_root, raise_fault
from samba_adws.errors import ADWSClientError
from src.soap.namespaces import SOAP_ENV, WSA


# Validates correlation and faults for a write; returns nothing on success.
#
# `_envelope.read_body` is deliberately not reused: it requires a non-empty
# body, which is right for a Get and wrong here, because a WS-Transfer
# DeleteResponse carries an empty one and is a success.
def parse_write_response(xml: str, expected_message_id: str, target: str,
                         expected_action: str) -> None:
    root = parse_root(xml, target)
    _check_correlation(root, expected_message_id, target)
    fault = _fault_in(root)
    if fault is not None:
        raise_fault(fault, target)
    check_action(root, expected_action, target)


# Refuses a response that answers a different request than the one sent.
def _check_correlation(root: ET.Element, expected_message_id: str, target: str) -> None:
    relates_to = root.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}RelatesTo")
    if relates_to != expected_message_id:
        raise ADWSClientError("ADWS response RelatesTo does not match",
                              "CorrelationError", target)


# The SOAP fault a response carries, if it carries one.
def _fault_in(root: ET.Element) -> Optional[ET.Element]:
    body = root.find(f"./{{{SOAP_ENV}}}Body")
    if body is None:
        return None
    return body.find(f"./{{{SOAP_ENV}}}Fault")
