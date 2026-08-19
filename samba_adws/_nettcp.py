"""Production Net.TCP transport backed by the existing NMF and GSSAPI streams."""

import socket
from typing import Any

from samba_adws._request import endpoint_for
from src.nettcp.stream.nmf import NMFStream
from src.nettcp.stream.socket import SocketStream


# Runs an authenticated NMF session against the ADWS Resource endpoint.
class NetTcpTransport:
    _stream: Any

    # Connects, performs the NMF preamble, and authenticates from the Kerberos cache.
    def __init__(self, server: str, port: int, timeout: float) -> None:
        raw_socket = socket.create_connection((server, port), timeout=timeout)
        raw_socket.settimeout(timeout)
        try:
            server_name = f"host@{server.rstrip('.')}"
            self._stream = NMFStream(
                SocketStream(raw_socket), endpoint_for(server, port), server_name
            )
            self._stream.preamble()
        except Exception:
            raw_socket.close()
            raise

    # Sends one sized WCF envelope and reads its correlated response.
    def exchange(self, payload: bytes) -> bytes:
        self._stream.write(payload)
        response: bytes = self._stream.read()
        return response

    # Sends the NMF end record and closes the socket.
    def close(self) -> None:
        self._stream.close()
