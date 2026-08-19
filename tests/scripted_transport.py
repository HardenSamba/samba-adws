"""Scripted transport support for offline ADWS client tests."""

from typing import Callable, List


# Records requests and returns responses produced by an offline script.
class ScriptedTransport:
    requests: List[bytes]
    closed: bool

    # Stores the response script without performing network activity.
    def __init__(self, script: Callable[[bytes], bytes]) -> None:
        self._script = script
        self.requests = []
        self.closed = False

    # Records one request and invokes the configured response script.
    def exchange(self, payload: bytes) -> bytes:
        self.requests.append(payload)
        return self._script(payload)

    # Marks the scripted session as closed.
    def close(self) -> None:
        self.closed = True
