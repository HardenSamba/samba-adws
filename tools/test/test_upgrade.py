#!/usr/bin/env python3
"""The security upgrade a client requests is compared before it is granted."""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The directory bindings are absent off a domain controller, and importing the
# protocol handler pulls them in. Only the refusal path is exercised here, and
# it returns before any of them is touched, so a stub is enough to import.
# A real controller has the real modules and keeps them.
for _name in ("gssapi", "ldb", "samba", "samba.param", "samba.credentials",
              "samba.gensec", "samba.auth", "samba.samdb", "samba.dcerpc",
              "samba.ndr", "samba.dsdb"):
    try:
        importlib.import_module(_name)
    except ImportError:
        sys.modules.setdefault(_name, MagicMock())

from classes.server import upgrade_check  # noqa: E402
from classes.server.protocol import ProtocolHandler  # noqa: E402
from src.nettcp import nmf  # noqa: E402

nmf.register_types()


class RecordingStream:
    """Serves one encoded record and keeps everything written back."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.written: List[bytes] = []

    def read(self, count: Optional[int] = None) -> bytes:
        if count is None:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:count], self._data[count:]
        return data

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def close(self) -> None:
        pass


def upgrade_request(protocol: str) -> bytes:
    encoded = protocol.encode("utf-8")
    record = nmf.UpgradeRequestRecord(
        UpgradeProtocolLength=len(encoded), UpgradeProtocol=protocol)
    written: Any = record.to_bytes()
    return bytes(written)


def handler(stream: RecordingStream) -> ProtocolHandler:
    log = logging.getLogger("test.upgrade")
    log.addHandler(logging.NullHandler())
    return ProtocolHandler(stream, log, "10.0.0.5:52344")


def test_the_expected_upgrade_is_accepted() -> None:
    """The value this repository's own client sends must keep passing."""
    record = nmf.UpgradeRequestRecord(UpgradeProtocol=upgrade_check.EXPECTED_UPGRADE)
    assert upgrade_check.is_supported(record)


def test_another_upgrade_is_refused() -> None:
    """Deleting the comparison in upgrade_check makes this fail."""
    assert not upgrade_check.is_supported(
        nmf.UpgradeRequestRecord(UpgradeProtocol="application/ssl-tls"))
    assert not upgrade_check.is_supported(nmf.UpgradeRequestRecord())


def test_the_comparison_is_exact() -> None:
    """The .NET client sends the literal string and compares it ordinally."""
    for near in ("Application/Negotiate", " application/negotiate",
                 "application/negotiate ", "application/negotiate\x00"):
        assert not upgrade_check.is_supported(nmf.UpgradeRequestRecord(UpgradeProtocol=near))


def test_a_refused_upgrade_never_gets_an_upgrade_response() -> None:
    """0x0A grants the upgrade; a client asking for ssl-tls must never see it."""
    stream = RecordingStream(upgrade_request("application/ssl-tls"))
    assert handler(stream).handle_security() is False
    sent = b"".join(stream.written)
    assert nmf.UpgradeResponseRecord().to_bytes() not in sent
    assert sent.startswith(b"\x08")
    assert upgrade_check.UPGRADE_INVALID.encode("utf-8") in sent


def test_a_refusal_logs_the_peer_and_the_requested_value(
        caplog: pytest.LogCaptureFixture) -> None:
    """One line, at WARNING, naming both."""
    stream = RecordingStream(upgrade_request("application/ssl-tls"))
    with caplog.at_level(logging.WARNING, logger="test.upgrade"):
        handler(stream).handle_security()
    lines = [r for r in caplog.records if "upgrade" in r.getMessage().lower()]
    assert len(lines) == 1
    assert "10.0.0.5:52344" in lines[0].getMessage()
    assert "application/ssl-tls" in lines[0].getMessage()


def test_a_long_requested_value_is_truncated_in_the_log() -> None:
    """The value is chosen by an unauthenticated peer; it does not run free."""
    rendered = upgrade_check.describe(
        nmf.UpgradeRequestRecord(UpgradeProtocol="a" * 4096))
    assert len(rendered) < 200
    assert "4096 chars" in rendered
