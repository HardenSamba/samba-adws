"""
Ceiling on the innermost socket stream
Every inbound length is bounded before it is allocated, and a short read is
reported rather than silently truncating the message.
"""

import logging
from typing import Any, Optional

from src.nettcp.nmf import MessageSizeExceeded


# Wraps the socket stream so that no read allocates more than the configured
# ceiling. It sits below GENSECStream, which replaces the protocol handler's
# stream after the security upgrade, so the pre-authentication records are
# covered as well as the message records.
class LimitedStream:

    # Binds a wrapped stream to the ceiling and to the peer it applies to.
    def __init__(self, inner: Any, limit: int, peer: str,
                 logger: logging.Logger) -> None:
        self._inner = inner
        self._limit = limit
        self._peer = peer
        self._logger = logger

    # Refuses an announced length above the ceiling before reading any of it,
    # and refuses a partial read, which would otherwise surface much later as
    # a parse error with no connection to its cause.
    def read(self, count: Optional[int] = None) -> bytes:
        if count is not None and count > self._limit:
            self._logger.warning(
                f"[LIMIT] {self._peer} announced {count} bytes, "
                f"maximum is {self._limit}")
            raise MessageSizeExceeded(
                f"announced length {count} exceeds maximum {self._limit}")
        data: bytes = self._inner.read(count)
        if count is not None and 0 < len(data) < count:
            raise EOFError(
                f"truncated read: {len(data)} of {count} bytes before the peer stopped")
        return data

    # Passes writes through untouched: the ceiling bounds inbound data only,
    # and the responses this server produces are its own business.
    def write(self, data: bytes) -> None:
        self._inner.write(data)

    # Closes the wrapped stream.
    def close(self) -> None:
        self._inner.close()
