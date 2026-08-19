#!/usr/bin/env python3
# encoding: utf-8
# Copyright 2016 Timo Schmid
from __future__ import print_function, unicode_literals, absolute_import

import logging
import sys

log = logging.getLogger(__name__ + '.SocketStream')

try:
    from helperlib import print_hexdump
except ImportError:
    print_hexdump = False
    log.debug('python-helperlib is unavailable; hexadecimal dumps are disabled')


class SocketStream:
    def __init__(self, socket):
        self._socket = socket

    def read(self, count=None):
        data = b''
        if count is None:
            data = self._socket.recv(4096)
        else:
            while count:
                d = self._socket.recv(count)
                if not d:
                    break
                count -= len(d)
                data += d

        if log.isEnabledFor(logging.DEBUG) and print_hexdump is not False:
            log.debug('Recved Data:')
            print_hexdump(data, colored=True, file=sys.stderr)
        return data

    def write(self, data):
        if log.isEnabledFor(logging.DEBUG) and print_hexdump is not False:
            log.debug('Sent Data:')
            print_hexdump(data, colored=True, file=sys.stderr)

        self._socket.sendall(data)

    def close(self):
        # self._socket.shutdown()
        self._socket.close()
