"""
Centralized configuration for ADWS server
"""

import logging
import logging.handlers
import os
from dataclasses import dataclass
from typing import Optional

from src.nettcp.nmf import MAX_MESSAGE_SIZE as DEFAULT_MAX_MESSAGE_SIZE


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 9389
    max_connections: int = 128
    timeout: int = 300
    max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE


@dataclass
class SambaConfig:
    """Samba AD configuration"""
    admin_user: Optional[str] = None
    admin_password: Optional[str] = None
    realm: Optional[str] = None


@dataclass
class LogConfig:
    """Logging configuration"""
    level: int = logging.INFO
    file: str = "adws.log"
    max_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Config:
    """Main configuration class"""

    def __init__(self) -> None:
        self.server = ServerConfig(
            host=os.environ.get("ADWS_HOST", "0.0.0.0"),
            port=int(os.environ.get("ADWS_PORT", "9389")),
            max_message_size=int(os.environ.get(
                "ADWS_MAX_MESSAGE_SIZE", str(DEFAULT_MAX_MESSAGE_SIZE))))
        self.samba = SambaConfig(realm=os.environ.get("ADWS_REALM"))
        self.logging = LogConfig(
            file=os.environ.get("ADWS_LOG_FILE", "adws.log"),
            level=getattr(logging, os.environ.get("ADWS_LOG_LEVEL", "INFO").upper(),
                          logging.INFO))
        self._logger: Optional[logging.Logger] = None

    def setup_logging(self) -> logging.Logger:
        """Setup centralized logging"""
        if self._logger:
            return self._logger

        logger = logging.getLogger("adws")
        logger.setLevel(self.logging.level)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(self.logging.format)
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        # File handler
        file_handler = logging.handlers.RotatingFileHandler(
            self.logging.file,
            maxBytes=self.logging.max_size,
            backupCount=self.logging.backup_count
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(self.logging.format)
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        self._logger = logger
        return logger

    def get_logger(self, name: str) -> logging.Logger:
        """Get logger for module"""
        if not self._logger:
            self.setup_logging()
        return logging.getLogger(f"adws.{name}")
