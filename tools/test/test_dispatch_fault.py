#!/usr/bin/env python3
"""A fault relates to its request, even when the request never parsed."""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The directory bindings are absent off a domain controller and the dispatcher
# imports them. Nothing here reaches a handler, so a stub is enough to import.
# A real controller has the real modules and keeps them.
for _name in ("ldb", "samba", "samba.param", "samba.credentials", "samba.gensec",
              "samba.auth", "samba.samdb", "samba.dcerpc", "samba.ndr",
              "samba.dsdb", "gssapi"):
    try:
        importlib.import_module(_name)
    except ImportError:
        sys.modules.setdefault(_name, MagicMock())

from classes.faults.exceptions import ADWSUnrelatableRequestException  # noqa: E402
from classes.handlers.dispatcher import ADWSDispatcher  # noqa: E402
from classes.parsing import message_id  # noqa: E402

WSA = "http://www.w3.org/2005/08/addressing"
SOAP = "http://www.w3.org/2003/05/soap-envelope"

# Well formed as far as the MessageID header, then truncated mid-element.
MALFORMED = (
    f'<s:Envelope xmlns:s="{SOAP}" xmlns:a="{WSA}"><s:Header>'
    '<a:Action>http://schemas.microsoft.com/2008/1/ActiveDirectory/Get</a:Action>'
    '<a:MessageID>urn:uuid:test-1</a:MessageID>'
    '</s:Header><s:Body><Broken'
)

WELL_FORMED = (
    f'<s:Envelope xmlns:s="{SOAP}" xmlns:a="{WSA}"><s:Header>'
    '<a:Action>http://example.invalid/NoSuchAction</a:Action>'
    '<a:MessageID>urn:uuid:test-2</a:MessageID>'
    '</s:Header><s:Body/></s:Envelope>'
)


class FakeRecord:
    """Stands in for a SizedEnvelopedMessageRecord already off the wire."""

    def __init__(self, xml: Optional[str]) -> None:
        self._xml = xml

    def payload_to_xml(self) -> str:
        if self._xml is None:
            raise ValueError("payload is not WCF binary XML")
        return self._xml


def dispatcher(monkeypatch: pytest.MonkeyPatch) -> ADWSDispatcher:
    log = logging.getLogger("test.dispatch")
    log.addHandler(logging.NullHandler())
    monkeypatch.setattr(
        ADWSDispatcher, "_encode_response",
        staticmethod(lambda xml: xml.encode("utf-8")))
    return ADWSDispatcher(log, session_info=None, peer="10.0.0.5:52344")


def test_a_fault_relates_to_a_request_that_never_parsed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect: context was None, so RelatesTo came out empty."""
    answer: Any = dispatcher(monkeypatch).dispatch(FakeRecord(MALFORMED), 0)
    assert b"<a:RelatesTo>urn:uuid:test-1</a:RelatesTo>" in answer
    assert b"<a:RelatesTo></a:RelatesTo>" not in answer


def test_an_unknown_action_still_relates_to_its_request(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The path that already worked, pinned so a refactor cannot break it."""
    answer: Any = dispatcher(monkeypatch).dispatch(FakeRecord(WELL_FORMED), 0)
    assert b"<a:RelatesTo>urn:uuid:test-2</a:RelatesTo>" in answer
    assert b"Unknown action" in answer


def test_an_undecodable_payload_closes_instead_of_faulting(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No MessageID exists anywhere, so no fault could be related to it."""
    with pytest.raises(ADWSUnrelatableRequestException):
        dispatcher(monkeypatch).dispatch(FakeRecord(None), 0)


def test_the_refusal_names_the_peer(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """One WARNING line saying which failure class was hit, and for whom."""
    with caplog.at_level(logging.WARNING, logger="test.dispatch"):
        with pytest.raises(ADWSUnrelatableRequestException):
            dispatcher(monkeypatch).dispatch(FakeRecord(None), 0)
    lines = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(lines) == 1
    assert "10.0.0.5:52344" in lines[0].getMessage()
    assert "no recoverable MessageID" in lines[0].getMessage()


def test_the_extractor_reads_a_prefixed_or_bare_element() -> None:
    """The document did not parse, so the prefix cannot be assumed."""
    assert message_id.extract("<a:MessageID>urn:uuid:x</a:MessageID>") == "urn:uuid:x"
    assert message_id.extract("<MessageID>urn:uuid:y</MessageID>") == "urn:uuid:y"
    assert message_id.extract("<wsa:MessageID >urn:uuid:z</wsa:MessageID>") == "urn:uuid:z"
    assert message_id.extract("<a:MessageID/>") == ""
    assert message_id.extract("no header here") == ""
    assert message_id.extract(None) == ""


def test_the_extractor_refuses_a_value_a_peer_could_run_away_with() -> None:
    """Its input is attacker controlled and its output goes into a header."""
    huge = "<a:MessageID>" + "u" * 4096 + "</a:MessageID>"
    assert message_id.extract(huge) == ""
    buried = " " * (message_id.SCAN_LIMIT + 1) + "<a:MessageID>urn:uuid:late</a:MessageID>"
    assert message_id.extract(buried) == ""
