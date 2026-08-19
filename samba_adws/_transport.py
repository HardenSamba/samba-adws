"""Transport boundary used by the public client and offline tests."""

from typing import Protocol


# Describes a single-request ADWS transport session.
class ClientTransport(Protocol):
    # Sends one WCF request and returns its WCF response.
    def exchange(self, payload: bytes) -> bytes:
        ...

    # Closes the underlying protocol session.
    def close(self) -> None:
        ...


# Opens the production Net.TCP transport lazily to keep imports workstation-safe.
def open_transport(server: str, port: int, timeout: float) -> ClientTransport:
    from samba_adws._nettcp import NetTcpTransport

    return NetTcpTransport(server, port, timeout)
