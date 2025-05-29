# File: utils/logging_setup.py

import logging
import sys
import os # Import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = "INFO", log_to_file: bool = False, log_dir: str = "logs", log_file_name: str = "bot.log"): # Added log_dir
    """
    Configures logging for the application.
    """
    numeric_log_level = getattr(logging, log_level.upper(), logging.INFO)

    # Base configuration
    log_format = "%(asctime)s [%(levelname)s] [%(name)s] (%(filename)s:%(lineno)d): %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_to_file:
        # Ensure the log directory exists
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                # Fallback to current directory if cannot create log_dir
                logging.error(f"Could not create log directory {log_dir}: {e}. Logging to current directory instead.")
                log_dir = "." # Log to current directory as a fallback

        full_log_path = os.path.join(log_dir, log_file_name)
        
        # Add a rotating file handler
        file_handler = RotatingFileHandler(
            full_log_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8' # 10MB per file, 5 backups
        )
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
        handlers.append(file_handler)

    logging.basicConfig(
        level=numeric_log_level,
        format=log_format,
        datefmt=date_format,
        handlers=handlers
    )

    # Suppress overly verbose logs from third-party libraries if necessary
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__) # Get a logger for this module
    logger.info(f"Logging configured with level {log_level.upper()}.")
    if log_to_file:
        logger.info(f"Logging to file: {full_log_path if 'full_log_path' in locals() else 'current_directory/bot.log'}")