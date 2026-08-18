#!/usr/bin/env python3
"""SambaAD ADWS server entry point (run with: python3 -m src.main)."""
from classes.server.config import Config
from classes.server.server import ADWSServer
from src.nettcp import nmf


# Builds the config, registers NMF record types, then runs the ADWS server.
def main() -> None:
    config = Config()
    logger = config.setup_logging()
    logger.info("=" * 60)
    logger.info("SambaAD ADWS Server Starting")
    logger.info("=" * 60)
    nmf.register_types()
    logger.info("NMF protocol registered")
    server = ADWSServer(config)
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        server.stop()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
