#!/usr/bin/env python3
"""SoapEnvelope: the header every response carries."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from classes.soap.soap_envelope import SoapEnvelope

WSA = "{http://www.w3.org/2005/08/addressing}"


def header(xml: str, name: str) -> str:
    found = ET.fromstring(xml).find(f".//{WSA}{name}")
    assert found is not None, f"{name} missing from {xml[:200]}"
    return found.text or ""


def test_a_response_relates_to_its_request(awkward: str) -> None:
    """CLAUDE.md 5: without this the cmdlet waits for its own timeout."""
    xml = SoapEnvelope.wrap("urn:test:Action", "urn:uuid:abc-1", "<x/>")
    assert header(xml, "RelatesTo") == "urn:uuid:abc-1"
    assert header(xml, "Action") == "urn:test:Action"


def test_an_awkward_action_and_message_id_survive(awkward: str) -> None:
    """Both go through html.escape, so both have to come back unchanged."""
    xml = SoapEnvelope.wrap(awkward, awkward, "<x/>")
    assert header(xml, "Action") == awkward
    assert header(xml, "RelatesTo") == awkward


def test_a_fault_carries_its_reason_verbatim(awkward: str) -> None:
    """A fault reason quotes what went wrong, which is often user input."""
    xml = SoapEnvelope.fault("urn:uuid:abc-2", "s:Receiver", awkward)
    root = ET.fromstring(xml)
    text = root.find(".//{http://www.w3.org/2003/05/soap-envelope}Text")
    assert text is not None
    assert text.text == awkward
    assert header(xml, "RelatesTo") == "urn:uuid:abc-2"


def test_a_fault_reparses_as_xml(awkward: str) -> None:
    """Substring assertions pass on malformed output; parsing does not."""
    ET.fromstring(SoapEnvelope.fault("urn:uuid:abc-3", "s:Sender", awkward,
                                     subcode="ad:UnknownThing"))


def test_an_empty_relates_to_stays_empty_rather_than_becoming_none() -> None:
    """A request may legitimately omit MessageID; that is not this bug."""
    assert header(SoapEnvelope.wrap("urn:test:A", "", "<x/>"), "RelatesTo") == ""
