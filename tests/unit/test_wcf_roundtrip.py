#!/usr/bin/env python3
"""The WCF binary layer: XML in, records, bytes, records, XML out."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from io import BytesIO, StringIO

import pytest
from src.wcf.records import Record, dump_records, print_records
from src.wcf.records.text import escape
from src.wcf.xml2records import XMLParser

SIMPLE = '<Envelope xmlns="urn:test"><Body><Value>{}</Value></Body></Envelope>'


def round_trip(value: str) -> str:
    """Sends a value through encode and decode, and returns what came back."""
    document = SIMPLE.format(
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    encoded = dump_records(XMLParser.parse(document))
    out = StringIO()
    print_records(Record.parse(BytesIO(encoded)), fp=out)
    text = ET.fromstring(out.getvalue()).find(".//{urn:test}Value")
    assert text is not None
    return text.text or ""


def test_an_accented_value_survives_the_binary_round_trip(awkward: str) -> None:
    """The escaper stopped escaping non-ASCII for exactly this reason."""
    assert round_trip(awkward) == awkward


@pytest.mark.parametrize("value", ["<", ">", "&", '"', "'", "a<b&c>d", "créé", "société"])
def test_values_come_back_from_the_round_trip_unchanged(value: str) -> None:
    """An ampersand a client sent must not come back as an unparseable token."""
    assert round_trip(value) == value


def test_the_escaper_leaves_non_ascii_alone() -> None:
    """Reverting src/wcf/records/text.py to entity-escaping fails this."""
    assert escape("créé") == "créé"
    assert escape("société & co") == "société &amp; co"


def test_the_escaper_still_escapes_the_five_xml_characters() -> None:
    assert escape("<") == "&lt;"
    assert escape(">") == "&gt;"
    assert escape("&") == "&amp;"
    assert escape('"') == "&quot;"


def test_an_escaped_document_reparses() -> None:
    """Escaping that produces an unresolvable entity raises here, not later."""
    ET.fromstring(SIMPLE.format(escape("créé & <société>")))
