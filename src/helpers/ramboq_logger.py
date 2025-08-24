import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

import yaml

# Load configuration from YAML file
with open('setup/yaml/ramboq_logger.yaml', 'r', encoding='utf-8', errors='ignore') as file:
    deploy = yaml.safe_load(file)

# Extract log and Twilio settings from config
FILE_LOG_FILE = deploy['file_log_file']
ERROR_LOG_FILE = deploy['error_log_file']
FILE_LOG_LEVEL = int(deploy['file_log_level'])
ERROR_LOG_LEVEL = int(deploy['error_log_level'])
SHORT_FILE_LOG_FILE = deploy['short_file_log_file']
SHORT_ERROR_LOG_FILE = deploy['short_error_log_file']
CONSOLE_LOG_LEVEL = int(deploy['console_log_level'])
TWILIO_ALERT = deploy['twilio_alert']
TWILIO_ACCOUNT_SID = deploy['twilio_account_sid']
TWILIO_AUTH_TOKEN = deploy['twilio_auth_token']

# def send_twilio_alert(message):
#     """Send an alert via Twilio if enabled in configuration."""
#     if not TWILIO_ALERT:
#         return
#     try:
#         from twilio.rest import Client  # Import here to avoid dependency if not used
#         client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
#         client.messages.create(
#             body=message,
#             from_=f'{TWILIO_FROM_NUMBER}',
#             to=f'{TWILIO_TO_NUMBER}'
#         )
#     except Exception as e:
#         print(f"[TwilioHandler] Failed to send alert: {e}")


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
        pass
        # super().emit(record)
        # self._trim_file()

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

# # --- Twilio Handler ---
# class TwilioHandler(logging.Handler):
#     """Custom handler that sends Twilio alerts for error-level logs."""
#     def emit(self, record):
#         if record.levelno >= logging.ERROR:
#             send_twilio_alert(self.format(record))
# twilio_handler = TwilioHandler()
# twilio_handler.setLevel(logging.ERROR)
# twilio_handler.setFormatter(formatter)


# --- Queue Listener ---
# Processes logs asynchronously from queue to all handlers
queue_listener = QueueListener(
    log_queue,
    console_handler,
    log_file_handler,
    error_file_handler,
    short_log_file_handler,
    short_error_file_handler,
    # twilio_handler,
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
    os.chdir("..")  # Move up a directory for testing
    print("cwd:", os.getcwd())

    logger1 = get_logger("module1")
    logger2 = get_logger("module2")

    logger1.debug("Module 1 → Debug message (useful for developers)")
    logger2.info("Module 2 → Info message (general updates)")
    logger1.warning("Module 1 → Warning (potential issue)")
    logger2.error("Module 2 → Error occurred! (This will trigger Twilio alert if enabled)")

    shutdown_logger()
