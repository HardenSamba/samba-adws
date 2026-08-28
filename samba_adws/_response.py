"""SOAP response validation for the supported Get-by-DN operation."""

from typing import Mapping

from samba_adws._envelope import check_action, parse_root, read_body
from samba_adws._request import GET_RESPONSE_ACTION
from samba_adws._values import decode_body


# Validates correlation and returns the decoded Get response attributes.
def parse_get_response(xml: str, expected_message_id: str, target: str) -> Mapping[str, object]:
    root = parse_root(xml, target)
    body = read_body(root, expected_message_id, target)
    check_action(root, GET_RESPONSE_ACTION, target)
    return decode_body(body)
