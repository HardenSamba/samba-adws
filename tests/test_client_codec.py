"""Strict WCF response-decoding tests."""

import pytest

from samba_adws._codec import decode_xml
from samba_adws.errors import ADWSClientError

VALID_WCF = bytes.fromhex("0042b405400178b7046f006b0001")
SHORT_TEXT_WCF = bytes.fromhex("0042b405b7066f006b00")
ATTRIBUTE_AFTER_END_WCF = bytes.fromhex("0042b4054001780106b601b602620001")


# An unknown record cannot be skipped before an otherwise valid document.
def test_decode_xml_rejects_unknown_record_prefix() -> None:
    with pytest.raises(ADWSClientError) as raised:
        decode_xml(b"\x00\xff" + VALID_WCF[1:])
    assert raised.value.code == "MalformedResponse"


# Bytes after a complete document remain part of the validated WCF stream.
def test_decode_xml_rejects_trailing_unknown_record() -> None:
    with pytest.raises(ADWSClientError) as raised:
        decode_xml(VALID_WCF + b"\xff")
    assert raised.value.code == "MalformedResponse"


# A short record payload or incomplete element stack cannot produce a response.
@pytest.mark.parametrize("payload", [VALID_WCF[:-1], SHORT_TEXT_WCF])
def test_decode_xml_rejects_truncated_record(payload: bytes) -> None:
    with pytest.raises(ADWSClientError) as raised:
        decode_xml(payload)
    assert raised.value.code == "MalformedResponse"


# Unbalanced structure and attributes after an end record are rejected.
@pytest.mark.parametrize(
    "payload", [VALID_WCF + b"\x01", ATTRIBUTE_AFTER_END_WCF]
)
def test_decode_xml_rejects_unbalanced_structure(payload: bytes) -> None:
    with pytest.raises(ADWSClientError) as raised:
        decode_xml(payload)
    assert raised.value.code == "MalformedResponse"


# A five-byte dictionary length must contain a terminating continuation bit.
def test_decode_xml_rejects_unterminated_dictionary_size() -> None:
    malformed = b"\x80\x80\x80\x80\x80" + VALID_WCF[1:]
    with pytest.raises(ADWSClientError) as raised:
        decode_xml(malformed)
    assert raised.value.code == "MalformedResponse"
