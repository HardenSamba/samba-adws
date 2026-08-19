#!/usr/bin/env python3
"""NMF records: the framing every request and response is wrapped in."""
from __future__ import annotations

from typing import Any, Optional

import pytest
from src.nettcp import nmf

nmf.register_types()


class Stream:
    """Serves a fixed byte string one read at a time."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, count: Optional[int] = None) -> bytes:
        if count is None:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:count], self._data[count:]
        return data


def parse(record: Any) -> Any:
    """Encodes a record and reads it back through the stream parser."""
    return nmf.Record.parse_stream(Stream(record.to_bytes()))


def test_a_sized_message_survives_encode_and_decode() -> None:
    payload = b"\x00\x01\x02 body \xff"
    decoded = parse(nmf.SizedEnvelopedMessageRecord(Size=len(payload), Payload=payload))
    assert decoded.code == 0x06
    assert decoded.Payload == payload
    assert decoded.Size == len(payload)


def test_a_via_record_carries_its_url() -> None:
    url = "net.tcp://dc.example.invalid:9389/ActiveDirectoryWebServices/Windows/Resource"
    decoded = parse(nmf.ViaRecord(ViaLength=len(url), Via=url))
    assert decoded.Via == url


def test_an_upgrade_request_carries_its_protocol_name() -> None:
    name = "application/negotiate"
    decoded = parse(nmf.UpgradeRequestRecord(UpgradeProtocolLength=len(name),
                                             UpgradeProtocol=name))
    assert decoded.UpgradeProtocol == name


@pytest.mark.parametrize("record,code", [
    (nmf.PreambleEndRecord(), 0x0c),
    (nmf.PreambleAckRecord(), 0x0b),
    (nmf.EndRecord(), 0x07),
    (nmf.UpgradeResponseRecord(), 0x0A),
])
def test_the_single_byte_records_are_one_byte(record: Any, code: int) -> None:
    """A stray byte here desynchronises every record that follows."""
    assert record.to_bytes() == bytes([code])


@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 16383, 16384, 1048576])
def test_a_varint_encodes_and_decodes_to_itself(value: int) -> None:
    assert nmf.varint.stream(None, Stream(nmf.varint.encode(value))) == value


def test_a_non_ascii_via_url_survives_the_utf8_field() -> None:
    """The field is declared UTF-8; a byte length is not a character count."""
    url = "net.tcp://dc.société.invalid:9389/Resource"
    encoded = url.encode("utf-8")
    decoded = parse(nmf.ViaRecord(ViaLength=len(encoded), Via=url))
    assert decoded.Via == url
