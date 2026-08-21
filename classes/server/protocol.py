"""
Protocol handler - manages the three phases of net.tcp handshake
Phase 1: Preamble (Version, Mode, Via, Encoding)
Phase 2: Security (UpgradeRequest/Response, GSSAPI)
Phase 3: Messages (SizedEnvelopedMessageRecord)
"""

import logging
import socket
from typing import Any

from src.nettcp import nmf
from src.nettcp.nmf import MessageSizeExceeded
from src.nettcp.stream.gssapi import GENSECStream
from src.nettcp.stream.socket import SocketStream

from classes.handlers.dispatcher import ADWSDispatcher
from classes.server import upgrade_check

socket_timeout = socket.timeout


class ProtocolHandler:
    """Manages the three-phase net.tcp protocol handshake"""

    def __init__(self, stream: SocketStream, logger: logging.Logger,
                 peer: str = "") -> None:
        self.stream: Any = stream
        self.logger = logger
        self.peer = peer
        self.negotiated = False
        self.request_index = 0
        self.pending_upgrade: Any = None
        self.session_info: Any = None

    def handle_preamble(self) -> bool:
        """Phase 1: Handle preamble records (codes 0x00-0x0c)"""
        self.logger.info("\n[PREAMBLE] ─── PHASE 1: PREAMBLE NEGOTIATION ───")

        try:
            # Process preamble records
            while True:
                obj = nmf.Record.parse_stream(self.stream)
                code = getattr(obj, 'code', None)

                if code == 0x00:  # VersionRecord
                    self.logger.info("[PREAMBLE] ◀ VersionRecord received from client")
                elif code == 0x01:  # ModeRecord
                    self.logger.info("[PREAMBLE] ◀ ModeRecord received from client")
                elif code == 0x02:  # ViaRecord
                    self.logger.info("[PREAMBLE] ◀ ViaRecord received from client")
                elif code == 0x03:  # KnownEncodingRecord
                    self.logger.info("[PREAMBLE] ◀ KnownEncodingRecord received from client")
                elif code == 0x09:  # UpgradeRequestRecord - marks end of preamble!
                    self.logger.info("[PREAMBLE] ◀ UpgradeRequestRecord received (preamble end)")
                    # UpgradeRequestRecord signals end of preamble, process it in security phase
                    self.pending_upgrade = obj
                    self.logger.info("[PREAMBLE] ✓ Preamble complete\n")
                    return True
                elif code == 0x0c:  # PreambleEndRecord
                    self.logger.info("[PREAMBLE] ◀ PreambleEndRecord received from client")
                    self.logger.info("[PREAMBLE] ▶ Sending PreambleAckRecord to client")
                    self.send_record(nmf.PreambleAckRecord())
                    self.logger.info("[PREAMBLE] ✓ Preamble complete\n")
                    return True
                else:
                    self.logger.warning(f"[PREAMBLE] ⚠ Unexpected record code: {code:#04x}")
                    return False

        except MessageSizeExceeded:
            raise
        except Exception as e:
            self.logger.error(f"[PREAMBLE] ✗ Error: {str(e)}", exc_info=True)
            return False

    def handle_security(self) -> bool:
        """Phase 2: Handle security upgrade and GSSAPI negotiation"""
        self.logger.info("[SECURITY] ─── PHASE 2: SECURITY NEGOTIATION ───\n")

        try:
            # If UpgradeRequestRecord was received during preamble, use it
            if self.pending_upgrade:
                obj = self.pending_upgrade
                self.pending_upgrade = None
            else:
                # Otherwise read next record
                obj = nmf.Record.parse_stream(self.stream)

            code = getattr(obj, 'code', None)

            if code != 0x09:  # UpgradeRequestRecord
                self.logger.error(f"[SECURITY] ✗ Expected UpgradeRequestRecord, got {code:#04x}")
                return False

            self.logger.info("[SECURITY] ◀ UpgradeRequestRecord received from client")

            # [MC-NMF] 3.1.4.7: an unsupported upgrade closes the session and
            # may carry a Fault Record. Nothing is granted before this passes.
            if not upgrade_check.is_supported(obj):
                self.logger.warning(
                    f"[SECURITY] ✗ {self.peer} requested an unsupported upgrade: "
                    f"{upgrade_check.describe(obj)}")
                self.send_record(upgrade_check.fault_record())
                return False

            # Send upgrade response
            self.logger.info("[SECURITY] ▶ Sending UpgradeResponseRecord to client")
            self.send_record(nmf.UpgradeResponseRecord())

            # Perform GSSAPI negotiation
            self.logger.info("[SECURITY] → Starting GSSAPI negotiation...")
            self.stream = GENSECStream(self.stream)
            self.stream.negotiate_server()
            self.negotiated = True
            self.session_info = self.stream.session_info()
            if self.session_info is None:
                self.logger.error(
                    "[SECURITY] ✗ negotiation left no authenticated session")
                return False
            self.logger.info("[SECURITY] ✓ GSSAPI negotiation completed\n")

            return True

        except MessageSizeExceeded:
            raise
        except Exception as e:
            self.logger.error(f"[SECURITY] ✗ Error: {str(e)}", exc_info=True)
            return False

    def handle_messages(self, dispatcher: ADWSDispatcher) -> bool:
        """Phase 3: Handle message exchange"""
        self.logger.info("\n[MESSAGES] ─── PHASE 3: MESSAGE EXCHANGE ───\n")

        try:
            while True:
                try:
                    obj = nmf.Record.parse_stream(self.stream)
                except (socket_timeout, ConnectionResetError, BrokenPipeError):
                    # No more messages, client likely done
                    self.logger.debug("[MESSAGES] ⏱ Connection timeout (no more client messages)")
                    # Send EndRecord to properly close protocol
                    try:
                        self.logger.info("[MESSAGES] ▶ Sending EndRecord to client")
                        self.send_record(nmf.EndRecord())
                        self.logger.info("[MESSAGES] ✓ EndRecord sent, connection closing\n")
                    except Exception:
                        pass
                    return True
                except MessageSizeExceeded:
                    raise
                except (EOFError, OSError):
                    # Connection closed by client
                    self.logger.info("[MESSAGES] ◀ Connection closed by client\n")
                    return True

                code = getattr(obj, 'code', None)

                if code == 0x0c:  # PreambleEndRecord - end of preamble after GSSAPI
                    self.logger.debug(
                        "[MESSAGES] ◀ PreambleEndRecord received, sending PreambleAckRecord"
                    )
                    self.send_record(nmf.PreambleAckRecord())
                    continue

                if code == 0x06:  # SizedEnvelopedMessageRecord
                    self.logger.info(
                        f"\n[MESSAGES] ◀ MESSAGE #{self.request_index} received from client"
                    )
                    self.logger.info(f"[MESSAGES] Request payload size: {len(obj.Payload)} bytes")

                    # Dispatch request and get response
                    payload = dispatcher.dispatch(obj, self.request_index)

                    # Send response
                    self.logger.info(
                        f"[MESSAGES] ▶ SENDING message #{self.request_index} to client"
                    )
                    response = nmf.SizedEnvelopedMessageRecord(
                        Payload=payload,
                        Size=len(payload)
                    )
                    self.send_record(response)
                    self.logger.info(
                        f"[MESSAGES] Response payload size: {len(payload)} bytes (sent to client)\n"
                    )

                    # Reduce timeout after sending response - client should respond quickly
                    try:
                        self.stream._socket.settimeout(2)
                    except Exception:
                        pass

                    self.request_index += 1

                elif code == 0x07:  # EndRecord
                    self.logger.info("[MESSAGES] ◀ EndRecord received from client")
                    self.logger.info("[MESSAGES] ✓ Connection closing\n")
                    return True

                else:
                    self.logger.warning(f"[MESSAGES] ⚠ Unexpected record code: {code:#04x}")
                    return False

        except MessageSizeExceeded:
            raise
        except Exception as e:
            self.logger.error(f"[MESSAGES] ✗ Error: {str(e)}", exc_info=True)
            return False

    def send_record(self, record: nmf.Record) -> None:
        """Send a single NMF record"""
        data = record.to_bytes()
        record_name = record.__class__.__name__
        self.logger.debug(f"[SEND] {record_name} ({len(data)} bytes)")
        self.stream.write(data)

