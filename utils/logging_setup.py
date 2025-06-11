# File: utils/logging_setup.py

import logging
import sys
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = "INFO", log_to_file: bool = False, log_dir: str = "logs", log_file_name: str = "bot.log"):
    """
    Configures logging for the application, including console output,
    optional file logging with rotation, and suppression of noisy third-party libraries.
    """
    numeric_log_level = getattr(logging, log_level.upper(), logging.INFO)

    # Base configuration for all handlers
    log_format = "%(asctime)s [%(levelname)s] [%(name)s] (%(filename)s:%(lineno)d): %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, date_format)

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_log_level)

    # Clear existing handlers to prevent duplicate messages if setup is called multiple times
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File Handler (if enabled)
    if log_to_file:
        # Ensure the log directory exists
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                logging.error(f"Could not create log directory {log_dir}: {e}. Logging to current directory instead.")
                log_dir = "." # Fallback to current directory

        full_log_path = os.path.join(log_dir, log_file_name)
        
        file_handler = RotatingFileHandler(
            full_log_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8' # 10MB per file, 5 backups
        )
        file_handler.setFormatter(formatter) # Use the same formatter
        root_logger.addHandler(file_handler)

    # Suppress overly verbose logs from specific third-party libraries
    # Set their log level to WARNING or ERROR to reduce noise
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING) # Dependency of httpx
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING) # Add if you're using it

    # Set specific levels for your application's loggers (optional, as root covers it)
    # This ensures your own code's messages always show at the configured level
    logging.getLogger('main').setLevel(numeric_log_level)
    logging.getLogger('config').setLevel(numeric_log_level)
    logging.getLogger('bot').setLevel(numeric_log_level)
    logging.getLogger('cogs.admin_commands_cog').setLevel(numeric_log_level)
    logging.getLogger('cogs.event_listeners_cog').setLevel(numeric_log_level)
    logging.getLogger('cogs.user_commands_cog').setLevel(numeric_log_level)
    logging.getLogger('llm_integration.llm_client').setLevel(numeric_log_level)
    logging.getLogger('services.verification_flow_service').setLevel(numeric_log_level)
    logging.getLogger('utils.logging_setup').setLevel(numeric_log_level) # For this file itself

    # Get a logger for this module to confirm setup
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured with level {log_level.upper()}.")
    if log_to_file:
        logger.info(f"Logging to file: {full_log_path if 'full_log_path' in locals() else 'current_directory/bot.log'}")