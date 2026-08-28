"""One client connection, carried through the three protocol phases."""

import logging
from socketserver import BaseRequestHandler
from typing import Any

from src.nettcp.nmf import MessageSizeExceeded
from src.nettcp.stream.socket import SocketStream

from classes.handlers.dispatcher import ADWSDispatcher
from classes.server import identity
from classes.server.limited_stream import LimitedStream
from classes.server.protocol import ProtocolHandler

BANNER = "=" * 70


# Handles one client connection, with each protocol phase kept separate.
class ConnectionHandler(BaseRequestHandler):

    config: Any
    logger: logging.Logger

    # Runs one connection and records how it ended.
    def handle(self) -> None:
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        self._edge("╔═ NEW CLIENT CONNECTION ═╗", peer)
        try:
            self.request.settimeout(10)
            self._serve(peer)
        except MessageSizeExceeded as e:
            self.logger.warning(f"[LIMIT] {peer} refused and disconnected: {e}")
        except (BrokenPipeError, ConnectionResetError, EOFError) as e:
            self.logger.info(f"[DISCONNECT] Client disconnected: {type(e).__name__}")
        except Exception as e:
            self.logger.exception(f"[ERROR] Unexpected error: {str(e)}")
        finally:
            self._edge("╚═ CONNECTION CLOSED ═╝", peer)

    # The phases in order, stopping at the first one that does not pass.
    #
    # Nothing is dispatched until the negotiated context has produced a session.
    # This used to build `system_session()` at that point instead, so a caller
    # was authenticated and then discarded, and every request that followed ran
    # with rights nobody had proved.
    def _serve(self, peer: str) -> None:
        self.stream = LimitedStream(
            SocketStream(self.request), self.config.server.max_message_size,
            peer, self.logger)
        phases = ProtocolHandler(self.stream, self.logger, peer)
        if not phases.handle_preamble():
            self.logger.warning("[PREAMBLE] Preamble negotiation failed")
            return
        if not phases.handle_security():
            self.logger.warning("[SECURITY] Security negotiation failed")
            return
        session_info = identity.required(phases.stream, self.logger, peer)
        if session_info is None:
            return
        dispatcher = ADWSDispatcher(self.logger, session_info=session_info, peer=peer)
        if not phases.handle_messages(dispatcher):
            self.logger.warning("[MESSAGES] Message exchange failed")

    # One boundary line in the connection log.
    def _edge(self, text: str, peer: str) -> None:
        self.logger.info(f"\n{BANNER}")
        self.logger.info(f"[CONNECTION] {text}")
        self.logger.info(f"[CONNECTION] Client: {peer}")
        self.logger.info(f"{BANNER}\n")
