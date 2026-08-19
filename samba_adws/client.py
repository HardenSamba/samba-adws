"""Public supported ADWS client."""

from typing import Mapping, Optional, Sequence

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._request import build_get_request
from samba_adws._response import parse_get_response
from samba_adws._transport import ClientTransport, open_transport
from samba_adws._validation import normalize_properties, validate_connection, validate_identity
from samba_adws.errors import ADWSClientError


# Retrieves directory objects through the Samba ADWS Resource endpoint.
class ADWSClient:
    server: str
    port: int
    timeout: float

    # Stores validated connection settings without opening a socket.
    def __init__(self, server: str, port: int = 9389, timeout: float = 30.0) -> None:
        validate_connection(server, port, timeout)
        self.server = server
        self.port = port
        self.timeout = float(timeout)

    # Retrieves one object by distinguished name with an optional projection.
    def get_by_dn(
        self, identity: str, properties: Sequence[str] = ()
    ) -> Mapping[str, object]:
        validate_identity(identity)
        try:
            requested = normalize_properties(properties)
            request, message_id = build_get_request(self.server, self.port, identity, requested)
            response = self._exchange(encode_xml(request), identity)
            return parse_get_response(decode_xml(response), message_id, identity)
        except ADWSClientError as error:
            if error.target is None:
                error.target = identity
            raise

    # Exchanges one payload and normalizes transport failures.
    def _exchange(self, payload: bytes, target: str) -> bytes:
        transport = None
        try:
            transport = open_transport(self.server, self.port, self.timeout)
            return transport.exchange(payload)
        except ADWSClientError:
            raise
        except Exception as error:
            message = str(error) or "ADWS transport failed"
            raise ADWSClientError(message, "TransportError", target) from error
        finally:
            self._close(transport)

    # Closes a transport without masking its request or response error.
    @staticmethod
    def _close(transport: Optional[ClientTransport]) -> None:
        if transport is None:
            return
        try:
            transport.close()
        except Exception:
            pass
