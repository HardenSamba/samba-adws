#!/usr/bin/env python3
"""ValueCodec: what an attribute value becomes on the wire."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from base64 import b64decode

import pytest
from classes.serialization.syntaxes import SyntaxRegistry
from classes.serialization.value_codec import ValueCodec
from src.serialization.syntax_constants import XSD_BASE64, XSD_STRING


@pytest.fixture
def codec() -> ValueCodec:
    return ValueCodec(SyntaxRegistry())


def reparsed(encoded: str) -> str:
    """Reads the text back through a parser, which is the only proof that counts."""
    return ET.fromstring(f"<v>{encoded}</v>").text or ""


def test_an_accented_value_survives_the_round_trip(codec: ValueCodec, awkward: str) -> None:
    """An entity ElementTree cannot resolve is how this broke the first time."""
    xsi, encoded = codec.encode_to_xsd("description", awkward.encode("utf-8"))
    assert xsi == XSD_STRING
    assert reparsed(encoded) == awkward


def test_the_five_predefined_entities_are_escaped_and_come_back(
        codec: ValueCodec) -> None:
    """Escaped on the way out, identical on the way back."""
    for value in ("<", ">", "&", '"', "'", "a<b&c>d"):
        _, encoded = codec.encode_to_xsd("description", value.encode("utf-8"))
        assert reparsed(encoded) == value


def test_a_control_byte_goes_to_base64_rather_than_into_the_xml(
        codec: ValueCodec) -> None:
    """XML 1.0 has no way to carry 0x01, so it must not be inserted at all."""
    raw = b"before\x01after"
    xsi, encoded = codec.encode_to_xsd("description", raw)
    assert xsi == XSD_BASE64
    assert b64decode(encoded) == raw


def test_bytes_that_are_not_utf8_go_to_base64(codec: ValueCodec) -> None:
    raw = b"\xff\xfe\x00\x01"
    xsi, encoded = codec.encode_to_xsd("description", raw)
    assert xsi == XSD_BASE64
    assert b64decode(encoded) == raw


def test_a_declared_binary_syntax_goes_to_base64(codec: ValueCodec) -> None:
    """objectSid is an octet string: base64 whatever its bytes happen to be."""
    xsi, encoded = codec.encode_to_xsd("objectSid", b"\x01\x05\x00\x00")
    assert xsi == XSD_BASE64
    assert b64decode(encoded) == b"\x01\x05\x00\x00"


def test_an_absent_value_is_an_empty_string(codec: ValueCodec) -> None:
    assert codec.encode_to_xsd("description", None) == (XSD_STRING, "")
