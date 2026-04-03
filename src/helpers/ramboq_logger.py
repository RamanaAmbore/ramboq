"""
Async queue-based logger with rotating file handlers.

Three outputs:
  1. Rotating log file  — full app log, 5 MB × 5 backups
  2. Rotating error file — errors only, small
  3. Console (stderr)

All handlers receive log records via a QueueListener so callers never block.
"""

import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

import yaml

# Read log config directly (no import of utils — avoids circular deps)
with open('setup/yaml/backend_config.yaml', encoding='utf-8', errors='ignore') as _f:
    _cfg = yaml.safe_load(_f)

_LOG_DIR = os.path.dirname(_cfg['file_log_file'])
os.makedirs(_LOG_DIR, exist_ok=True)

_FMT = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
_log_queue = queue.Queue()

# Rotating file handler — full log
_file_h = RotatingFileHandler(
    _cfg['file_log_file'], maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
_file_h.setLevel(int(_cfg['file_log_level']))
_file_h.setFormatter(_FMT)

# Rotating error handler — errors only
_err_h = RotatingFileHandler(
    _cfg['error_log_file'], maxBytes=5 * 1024, backupCount=5, encoding='utf-8')
_err_h.setLevel(int(_cfg['error_log_level']))
_err_h.setFormatter(_FMT)

# Console handler
_con_h = logging.StreamHandler()
_con_h.setLevel(int(_cfg['console_log_level']))
_con_h.setFormatter(_FMT)

# Async listener — drains queue to all handlers
_listener = QueueListener(_log_queue, _con_h, _file_h, _err_h, respect_handler_level=True)
_listener.start()


def get_logger(name: str = "app_logger") -> logging.Logger:
    """Return a logger wired to the async queue (idempotent)."""
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)
        logger.addHandler(QueueHandler(_log_queue))
    return logger


def shutdown_logger() -> None:
    """Flush and stop the queue listener (call at process exit)."""
    _listener.stop()
