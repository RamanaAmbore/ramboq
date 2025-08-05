import logging
from logging.handlers import RotatingFileHandler 


# Function to set up logging configuration
def log_setup():
    maxBytes = 40  # Maximum size (in bytes) of the log file before it gets rotated
    backupCount = 1  # Number of backup log files to keep after rotation

    # Get the logger instance for Streamlit
    log = logging.getLogger('streamlit')
    log.setLevel(logging.DEBUG)  # Set the minimum logging level to DEBUG
    log.propagate = False  # Prevent the logger from propagating messages to parent loggers

    # Define the format for the log messages
    format = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s", datefmt="%H:%M:%S")

    # Create a RotatingFileHandler for error logs with size limit and backup count
    error_file_handler = RotatingFileHandler(".log/streamlit_error_log.log",
                                             maxBytes=maxBytes, backupCount=backupCount)
    error_file_handler.setLevel(logging.INFO)  # Log messages of INFO level and higher
    error_file_handler.setFormatter(format)  # Apply the log format to the handler
    log.addHandler(error_file_handler)  # Add the handler to the logger

    # Create a RotatingFileHandler for debug logs
    debug_file_handler = RotatingFileHandler(".log/streamlit_debug_log.log",
                                             maxBytes=maxBytes, backupCount=backupCount)
    debug_file_handler.setLevel(logging.DEBUG)  # Log messages of DEBUG level and higher
    debug_file_handler.setFormatter(format)  # Apply the log format to the handler
    log.addHandler(debug_file_handler)  # Add the handler to the logger

    # Create a StreamHandler to log messages to the console (stdout)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)  # Log messages of DEBUG level and higher
    stream_handler.setFormatter(format)  # Apply the log format to the handler
    log.addHandler(stream_handler)  # Add the handler to the logger
