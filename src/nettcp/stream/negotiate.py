#!/usr/bin/env python3
# encoding: utf-8
# Copyright 2016 Timo Schmid
from __future__ import print_function, unicode_literals, absolute_import

import enum
import struct
from ..nmf import Record, MessageSizeExceeded
import logging

log = logging.getLogger(__name__ + '.NegotiateStream')

# The writer above never emits more than 0xFC30 bytes in one frame, so a peer
# announcing a larger frame is not following [MS-NNS]. The handshake frames
# carry their length as '>H' and are already bounded at 65535 by the format.
MAX_FRAME_SIZE = 0xFC30


class MessageType(enum.IntEnum):
    HANDSHAKE_DONE = 0x14
    HANDSHAKE_ERROR = 0x15
    HANDSHAKE_IN_PROGRESS = 0x16


class Handshake(Record):
    _records = {}


class HandshakeDone(Record):
    code = MessageType.HANDSHAKE_DONE
    fields = [
        ('major', 'B'),
        ('minor', 'B'),
        ('payload_size', '>H')
    ]


class HandshakeError(HandshakeDone):
    code = MessageType.HANDSHAKE_ERROR


class HandshakeInProgress(HandshakeDone):
    code = MessageType.HANDSHAKE_IN_PROGRESS

Handshake.register(HandshakeInProgress)
Handshake.register(HandshakeDone)
Handshake.register(HandshakeError)


class NegotiateStream:
    def __init__(self, stream):
        self._inner = stream
        self._handshake_done = False

    def write(self, data):
        if not self._handshake_done:
            handshake = HandshakeInProgress(
                                major=1,
                                minor=0,
                                payload_size=len(data)
                            ).to_bytes()
            self._inner.write(handshake + data)
        else:
            while data:
                data2 = data[:0xFC30]
                self._inner.write(struct.pack('<I', len(data2)) + data2)
                data = data[0xFC30:]

    def read(self, count=None):
        if not self._handshake_done:
            _, message = Handshake.parse(self._inner.read(5))

            if message.code == int(MessageType.HANDSHAKE_ERROR):
                error = None
                if message.payload_size > 0:
                    error = struct.unpack('>II', self._inner.read(8))[1]
                raise IOError("Negotiate Error: {:08x}".format(error))
            elif message.code == int(MessageType.HANDSHAKE_DONE):
                self._handshake_done = True
                log.debug('NNS Handshake done')

            return self._inner.read(message.payload_size)
        else:
            payload_size = struct.unpack('<I', self._inner.read(4))[0]
            if payload_size > MAX_FRAME_SIZE:
                raise MessageSizeExceeded(
                    'frame of {} bytes exceeds maximum {}'.format(
                        payload_size, MAX_FRAME_SIZE))
            return self._inner.read(payload_size)

    def write_handshake_done(self, data):
        self._handshake_done = True
        handshake = HandshakeDone(
                                major=1,
                                minor=0,
                                payload_size=len(data)
                            ).to_bytes()
        self._inner.write(handshake + data)

    def close(self):
        self._inner.close()
