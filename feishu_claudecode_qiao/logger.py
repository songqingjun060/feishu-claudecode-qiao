"""Logging setup with rotating file handlers."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    data_dir: str = "./data",
    log_level: str = "INFO",
) -> tuple[logging.Logger, logging.Logger]:
    """Configure bridge and message loggers.

    Returns:
        (bridge_logger, message_logger)
    """
    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Bridge logger – general application logs
    bridge_logger = logging.getLogger("feishu_qiao.bridge")
    bridge_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    for handler in list(bridge_logger.handlers):
        bridge_logger.removeHandler(handler)
        handler.close()

    bridge_file = RotatingFileHandler(
        log_dir / "bridge.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    bridge_file.setFormatter(fmt)
    bridge_logger.addHandler(bridge_file)

    bridge_console = logging.StreamHandler(sys.stdout)
    bridge_console.setFormatter(fmt)
    bridge_logger.addHandler(bridge_console)

    # Message logger – dedicated for message traffic
    message_logger = logging.getLogger("feishu_qiao.messages")
    message_logger.setLevel(logging.INFO)
    for handler in list(message_logger.handlers):
        message_logger.removeHandler(handler)
        handler.close()

    message_file = RotatingFileHandler(
        log_dir / "messages.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    message_file.setFormatter(fmt)
    message_logger.addHandler(message_file)

    return bridge_logger, message_logger
