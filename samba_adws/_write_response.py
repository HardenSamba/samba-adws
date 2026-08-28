"""Response validation for the directory-changing operations.

This module exists to say one thing: **an empty body is what success looks
like.** `_envelope.read_body` is deliberately not reused, because it requires a
non-empty body — which is right for a Get and wrong here. A WS-Transfer
PutResponse and DeleteResponse each carry an empty one and each is a success:
`classes/handlers/modify.py` and `classes/handlers/delete.py` both answer with
`envelope.wrap(REPLY_ACTION, message_id, "")`.

A client routed through `read_body` therefore reports `MalformedResponse` for
work the directory has already done — the object is renamed, the account is
deleted, and the caller is told it failed. That is the failure this file is
here to prevent, and it is invisible to any test whose scripted answer carries a
filler element no handler in `classes/handlers` ever emits.
"""

import xml.etree.ElementTree as ET
from typing import Optional

from src.soap.namespaces import AD, SOAP_ENV

from samba_adws._envelope import check_action, check_correlation, parse_root, raise_fault
from samba_adws.errors import ADWSClientError


# Validates one write response and returns its SOAP body, which may be absent.
#
# Correlation first, then the fault, then the action, for the reason
# `_envelope.read_body` gives: a fault answering a different request is still
# the wrong answer. The action check is what separates an acknowledgement of the
# verb that was sent from an acknowledgement of some other verb.
def parse_write_response(
    xml: str, expected_message_id: str, target: str, expected_action: str
) -> Optional[ET.Element]:
    root = parse_root(xml, target)
    check_correlation(root, expected_message_id, target)
    body = root.find(f"./{{{SOAP_ENV}}}Body")
    fault = None if body is None else body.find(f"./{{{SOAP_ENV}}}Fault")
    if fault is not None:
        raise_fault(fault, target)
    check_action(root, expected_action, target)
    return body


# Returns the objectGUID the directory reported for a newly created object.
#
# `CreateHandler._success` sends it as the objectReferenceProperty of the
# WS-Addressing ResourceCreated EPR, and going to that trouble is worth reading.
# A CreateResponse naming no object is refused rather than returned as a success
# with an empty identifier, which a caller would store and come back with later
# to find nothing there.
def created_guid(body: Optional[ET.Element], target: str) -> str:
    found = None if body is None else body.findtext(f".//{{{AD}}}objectReferenceProperty")
    if not found:
        raise ADWSClientError("The directory did not report the new object.",
                              "ProtocolError", target)
    return found
