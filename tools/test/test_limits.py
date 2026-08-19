#!/usr/bin/env python3
"""Inbound size ceilings: the varint decoder, the frame reader, the stream."""
from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from classes.server.limited_stream import LimitedStream  # noqa: E402
from src.nettcp import nmf  # noqa: E402


class FakeStream:
    """Serves a fixed byte string, counting what was asked for."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.requested: List[Optional[int]] = []

    def read(self, count: Optional[int] = None) -> bytes:
        self.requested.append(count)
        if count is None:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:count], self._data[count:]
        return data

    def write(self, data: bytes) -> None:
        raise AssertionError("the ceiling is for inbound data only")

    def close(self) -> None:
        pass


class EndlessStream:
    """Serves continuation bytes for ever, which is what a hostile peer is.

    It gives up after a bound so that a regression fails the suite instead of
    hanging it; the unbounded decoder had read 13.8 million bytes after three
    seconds and was still going.
    """

    def __init__(self, byte: bytes = b"\x80", bound: int = 64) -> None:
        self._byte = byte
        self._bound = bound
        self.reads = 0

    def read(self, count: Optional[int] = None) -> bytes:
        self.reads += 1
        if self.reads > self._bound:
            raise AssertionError(f"decoder read past {self._bound} bytes without stopping")
        return self._byte


def logger() -> logging.Logger:
    log = logging.getLogger("test.limits")
    log.addHandler(logging.NullHandler())
    return log


def test_varint_of_repeated_continuation_bytes_terminates() -> None:
    """Without the byte cap this never returns, and shifts an unbounded integer."""
    stream = EndlessStream()
    with pytest.raises(nmf.MessageSizeExceeded) as caught:
        nmf.varint_stream(None, stream)
    assert "varint longer than 5 bytes" in str(caught.value)
    assert stream.reads == nmf.MAX_VARINT_BYTES


def test_varint_above_the_ceiling_is_refused_before_any_payload_read() -> None:
    """A 5-byte varint decoding to 4 GiB is rejected, and nothing is read after it."""
    stream = FakeStream(b"\x80\x80\x80\x80\x10")
    with pytest.raises(nmf.MessageSizeExceeded) as caught:
        nmf.varint_stream(None, stream)
    assert str(nmf.MAX_MESSAGE_SIZE) in str(caught.value)
    assert stream.requested == [1, 1, 1, 1, 1]
    assert stream._data == b""


def test_a_size_above_the_ceiling_is_refused_without_allocating() -> None:
    """LimitedStream refuses the announced length before asking the socket for it."""
    inner = FakeStream(b"payload")
    stream = LimitedStream(inner, 1024, "10.0.0.5:52344", logger())
    with pytest.raises(nmf.MessageSizeExceeded) as caught:
        stream.read(4 * 1024 * 1024 * 1024)
    assert "4294967296" in str(caught.value)
    assert inner.requested == []


def test_a_short_read_is_reported_rather_than_truncated() -> None:
    """Returning three of eight bytes silently surfaces later as a parse error."""
    stream = LimitedStream(FakeStream(b"abc"), 1024, "10.0.0.5:52344", logger())
    with pytest.raises(EOFError):
        stream.read(8)


def test_a_read_within_the_ceiling_passes_through() -> None:
    """The ceiling must not disturb ordinary traffic, including a clean EOF."""
    inner = FakeStream(b"abcdefgh")
    stream = LimitedStream(inner, 1024, "10.0.0.5:52344", logger())
    assert stream.read(8) == b"abcdefgh"
    assert stream.read(4) == b""
    assert inner.requested == [8, 4]


def test_the_decoder_and_the_server_share_one_ceiling() -> None:
    """Two places read ADWS_MAX_MESSAGE_SIZE; they must not drift apart."""
    from classes.server.config import Config

    assert Config().server.max_message_size == nmf.MAX_MESSAGE_SIZE
