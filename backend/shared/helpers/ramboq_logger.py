import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path

import yaml

# Load configuration from YAML file (resolve relative to repo root)
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "backend" / "config" / "backend_config.yaml"
with open(_CONFIG_PATH, 'r', encoding='utf-8', errors='ignore') as file:
    deploy = yaml.safe_load(file)

# Optional prefix for log file names (set via RAMBOQ_LOG_PREFIX env var)
# Allows different API processes to write to distinct log files
_LOG_PREFIX = os.environ.get('RAMBOQ_LOG_PREFIX', '')

# Extract log settings from config
FILE_LOG_FILE = os.path.join(os.path.dirname(deploy['file_log_file']), _LOG_PREFIX + os.path.basename(deploy['file_log_file']))
ERROR_LOG_FILE = os.path.join(os.path.dirname(deploy['error_log_file']), _LOG_PREFIX + os.path.basename(deploy['error_log_file']))
FILE_LOG_LEVEL = int(deploy['file_log_level'])
ERROR_LOG_LEVEL = int(deploy['error_log_level'])
SHORT_FILE_LOG_FILE = os.path.join(os.path.dirname(deploy['short_file_log_file']), _LOG_PREFIX + os.path.basename(deploy['short_file_log_file']))
SHORT_ERROR_LOG_FILE = os.path.join(os.path.dirname(deploy['short_error_log_file']), _LOG_PREFIX + os.path.basename(deploy['short_error_log_file']))
CONSOLE_LOG_LEVEL = int(deploy['console_log_level'])


# Ensure log directory exists
os.makedirs(os.path.dirname(FILE_LOG_FILE), exist_ok=True)

# Create global log queue for asynchronous logging
log_queue = queue.Queue()

# Common formatter for all handlers
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# --- Rotating File Handlers ---
# Maintains multiple log files with size-based rotation
log_file_handler = RotatingFileHandler(
    FILE_LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5, encoding="utf-8"
)
log_file_handler.setLevel(FILE_LOG_LEVEL)
log_file_handler.setFormatter(formatter)

error_file_handler = RotatingFileHandler(
    ERROR_LOG_FILE,
    maxBytes=5 * 1024,  # ~5 KB (small log, only errors)
    backupCount=5,
    encoding="utf-8"
)
error_file_handler.setLevel(ERROR_LOG_LEVEL)
error_file_handler.setFormatter(formatter)


# --- Line-Limited Handlers ---
class LineLimitedFileHandler(logging.FileHandler):
    """
    Custom FileHandler that keeps only the last N lines.
    Useful for "short logs" where only recent activity matters.
    """

    def __init__(self, filename, mode='a', max_lines=100, encoding=None, delay=False):
        super().__init__(filename, mode, encoding, delay)
        self.max_lines = max_lines
        self.filename = filename

    def emit(self, record):
        super().emit(record)
        self._trim_file()

    def _trim_file(self):
        try:
            with open(self.filename, 'r', encoding=self.encoding or 'utf-8') as f:
                lines = f.readlines()
            if len(lines) > self.max_lines:
                with open(self.filename, 'w', encoding=self.encoding or 'utf-8') as f:
                    f.writelines(lines[-self.max_lines:])
        except Exception as e:
            print(f"[LineLimitedFileHandler] Failed to trim log file {self.filename}: {e}")


short_log_file_handler = LineLimitedFileHandler(
    SHORT_FILE_LOG_FILE,
    max_lines=50, encoding="utf-8"
)
short_log_file_handler.setLevel(FILE_LOG_LEVEL)
short_log_file_handler.setFormatter(formatter)

short_error_file_handler = LineLimitedFileHandler(
    SHORT_ERROR_LOG_FILE,
    max_lines=50, encoding="utf-8"
)
short_error_file_handler.setLevel(ERROR_LOG_LEVEL)
short_error_file_handler.setFormatter(formatter)

# --- Console Handler ---
console_handler = logging.StreamHandler()
console_handler.setLevel(CONSOLE_LOG_LEVEL)
console_handler.setFormatter(formatter)

# --- Queue Listener ---
# Processes logs asynchronously from queue to all handlers
queue_listener = QueueListener(
    log_queue,
    console_handler,
    log_file_handler,
    error_file_handler,
    short_log_file_handler,
    short_error_file_handler,
    respect_handler_level=True
)
queue_listener.start()


def get_logger(name="app_logger"):
    """
    Return a logger instance configured with queue handler.
    Ensures no duplicate handlers are added.
    """
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)  # Capture everything, handlers filter levels
        queue_handler = QueueHandler(log_queue)
        logger.addHandler(queue_handler)
    return logger


def shutdown_logger():
    """Gracefully stop the queue listener (to be called at shutdown)."""
    queue_listener.stop()


# --- Example usage ---
if __name__ == "__main__":

    logger1 = get_logger("module1")
    logger2 = get_logger("module2")

    logger1.debug("Module 1 → Debug message (useful for developers)")
    logger2.info("Module 2 → Info message (general updates)")
    logger1.warning("Module 1 → Warning (potential issue)")
    logger2.error("Module 2 → Error occurred!")

    shutdown_logger()
