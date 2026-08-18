"""
ADWS TCP Server - Entry point for handling client connections
"""

import socketserver
from typing import Any, Type

from classes.server.config import Config
from classes.server.connection import ConnectionHandler


class ADWSServer:
    """Main ADWS server class"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = config.get_logger("server")

        # Verify LDB modules are available
        self._verify_ldb_backends()

        # Create socket server with connection handler.
        # Defer bind/activate so SO_REUSEADDR is set BEFORE bind, otherwise a
        # TIME_WAIT socket on the port makes a restart fail with EADDRINUSE.
        self.server = socketserver.ForkingTCPServer(
            (config.server.host, config.server.port),
            self._create_handler_class(),
            bind_and_activate=False,
        )
        self.server.allow_reuse_address = True
        self.server.server_bind()
        self.server.server_activate()

    def _verify_ldb_backends(self) -> None:
        """Verify that needed LDB backends are available"""
        try:
            from samba.auth import system_session
            from samba.param import LoadParm

            self.logger.info("[LDB] Checking backends...")

            # Try to load config
            lp = LoadParm()
            lp.load_default()
            self.logger.info("[LDB] Samba config loaded OK")

            # Check for search module
            try:
                system_session()
                self.logger.info("[LDB] System session created OK")
            except Exception as e:
                self.logger.warning(f"[LDB] System session issue: {str(e)}")

            self.logger.info("[LDB] Backend verification passed")
        except Exception as e:
            self.logger.error(f"[LDB] Backend verification failed: {str(e)}")
            self.logger.error("[LDB] Samba/LDB modules may not be properly installed")

    def _create_handler_class(self) -> Type[socketserver.BaseRequestHandler]:
        """Create handler class with config injected"""
        config = self.config
        logger = self.logger

        class ConfiguredHandler(ConnectionHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.config = config
                self.logger = logger
                super().__init__(*args, **kwargs)

        return ConfiguredHandler

    def start(self) -> None:
        """Start the server"""
        self.logger.info(
            f"ADWS server started on {self.config.server.host}:{self.config.server.port}"
        )
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            self.logger.info("Server shutdown requested")
            self.stop()

    def stop(self) -> None:
        """Stop the server"""
        self.server.shutdown()
        self.server.server_close()
        self.logger.info("Server stopped")
