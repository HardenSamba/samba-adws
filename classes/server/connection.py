"""
Connection handler - manages individual client connections
Separates protocol phases for cleaner state management
"""

import logging
from socketserver import BaseRequestHandler
from typing import Any

from src.nettcp.nmf import MessageSizeExceeded
from src.nettcp.stream.socket import SocketStream

try:
    from samba.auth import system_session
except ImportError:
    system_session = None

from classes.handlers.dispatcher import ADWSDispatcher
from classes.server.limited_stream import LimitedStream
from classes.server.protocol import ProtocolHandler


class ConnectionHandler(BaseRequestHandler):
    """Handles individual client connections with clean protocol phases"""

    config: Any
    logger: logging.Logger

    def handle(self) -> None:
        """Main connection handler"""
        client_ip = self.client_address[0]
        client_port = self.client_address[1]
        self.logger.info(f"\n{'='*70}")
        self.logger.info("[CONNECTION] ╔═ NEW CLIENT CONNECTION ═╗")
        self.logger.info(f"[CONNECTION] Client: {client_ip}:{client_port}")
        self.logger.info(f"{'='*70}\n")

        try:
            # Set socket timeout to prevent indefinite blocking
            # 10 second timeout for initial connection, reduced after response
            self.request.settimeout(10)

            self.stream = LimitedStream(
                SocketStream(self.request), self.config.server.max_message_size,
                f"{client_ip}:{client_port}", self.logger)
            phase_handler = ProtocolHandler(
                self.stream, self.logger, f"{client_ip}:{client_port}")

            # Phase 1: Preamble negotiation (Version, Mode, Via, Encoding)
            if not phase_handler.handle_preamble():
                self.logger.warning("[PREAMBLE] Preamble negotiation failed")
                return

            # Phase 2: Security upgrade (GSSAPI)
            if not phase_handler.handle_security():
                self.logger.warning("[SECURITY] Security negotiation failed")
                return

            # Phase 3: Message exchange with authenticated session
            # Use system_session for SamDB context - auth is done via GSSAPI
            session_info = system_session() if system_session else None
            dispatcher = ADWSDispatcher(
                self.logger, session_info=session_info,
                peer=f"{client_ip}:{client_port}")
            if not phase_handler.handle_messages(dispatcher):
                self.logger.warning("[MESSAGES] Message exchange failed")
                return

        except MessageSizeExceeded as e:
            self.logger.warning(
                f"[LIMIT] {client_ip}:{client_port} refused and disconnected: {e}")
        except (BrokenPipeError, ConnectionResetError, EOFError) as e:
            self.logger.info(f"[DISCONNECT] Client disconnected: {type(e).__name__}")
        except Exception as e:
            self.logger.exception(f"[ERROR] Unexpected error: {str(e)}")
        finally:
            self.logger.info(f"\n{'='*70}")
            self.logger.info("[CONNECTION] ╚═ CONNECTION CLOSED ═╝")
            self.logger.info(f"[CONNECTION] Client: {client_ip}:{client_port}")
            self.logger.info(f"{'='*70}\n")
