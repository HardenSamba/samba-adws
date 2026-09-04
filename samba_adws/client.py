"""Public supported ADWS client."""

from typing import Mapping, Optional, Sequence

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._request import build_get_request
from samba_adws._response import parse_get_response
from samba_adws._root_dse import DEFAULT_NAMING_CONTEXT, ROOT_DSE_IDENTITY, naming_context_of
from samba_adws._transport import ClientTransport, open_transport
from samba_adws._validation import normalize_properties, validate_connection, validate_identity
from samba_adws.errors import ADWSClientError


# Retrieves directory objects through the Samba ADWS Resource endpoint.
class ADWSClient:
    server: str
    port: int
    timeout: float
    _held: Optional[ClientTransport]

    # Stores validated connection settings without opening a socket.
    def __init__(self, server: str, port: int = 9389, timeout: float = 30.0) -> None:
        validate_connection(server, port, timeout)
        self.server = server
        self.port = port
        self.timeout = float(timeout)
        self._held = None

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

    # Returns one naming context published by the RootDSE.
    #
    # The only question a caller can ask before it knows anything: a search
    # needs a base, and a console never holds a distinguished name until
    # something published one.
    #
    # `kind` names an attribute that holds a single distinguished name. The
    # multi-valued `namingContexts` is refused rather than reduced to whichever
    # value came first, because this returns one context and cannot say so.
    def naming_context(self, kind: str = DEFAULT_NAMING_CONTEXT) -> str:
        return naming_context_of(self.get_by_dn(ROOT_DSE_IDENTITY, (kind,)), kind)

    # Exchanges one payload and normalizes transport failures.
    #
    # A sequence whose messages must reach one server process opens the
    # connection itself and parks it in `_held`; this then borrows it and
    # leaves it open. `ADWSSearchClient.page` says why that is not optional.
    def _exchange(self, payload: bytes, target: str) -> bytes:
        held = self._held
        transport: Optional[ClientTransport] = held
        try:
            if transport is None:
                transport = open_transport(self.server, self.port, self.timeout)
            return transport.exchange(payload)
        except ADWSClientError:
            raise
        except Exception as error:
            message = str(error) or "ADWS transport failed"
            raise ADWSClientError(message, "TransportError", target) from error
        finally:
            if held is None:
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
