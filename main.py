# File: main.py

import asyncio
import discord # Keep for intents if not directly used by VerificationBot instantiation
from discord.ext import commands
import logging

# Load settings first to ensure they are available globally if needed
# and to catch configuration errors early.
try:
    from config import settings # Settings are loaded here
except SystemExit as e:
    logging.critical(f"Bot cannot start due to critical configuration errors: {e}")
    # logger might not be configured yet if config itself fails hard.
    print(f"CRITICAL: Bot cannot start due to critical configuration errors: {e}")
    exit(1)
except ImportError: # Handle if config.py itself is missing or has issues
    logging.critical("Failed to import settings from config.py. Ensure config.py exists and is valid.")
    print("CRITICAL: Failed to import settings from config.py. Ensure config.py exists and is valid.")
    exit(1)


from utils.logging_setup import setup_logging
from bot import VerificationBot # Import the bot class from bot.py

# Setup logging using the level from settings
setup_logging(log_level=settings.LOG_LEVEL, log_to_file=True) 

# Get the root logger AFTER setup
logger = logging.getLogger(__name__)

# Define Intents - these are passed to the Bot constructor
intents = discord.Intents.default()
intents.members = True      # Required for on_member_join, member updates, and fetching members.
intents.guilds = True       # Required for guild information, roles, channels.
intents.message_content = True # Required to read message content, especially in DMs for verification.


async def main():
    # The VerificationBot instance will load settings from the imported 'settings' object
    bot_instance = VerificationBot(
        command_prefix=commands.when_mentioned_or("!verify "), # Fallback, primarily slash commands
        intents=intents,
        help_command=None # Disable default help command
    )

    async with bot_instance: # Uses the bot as an asynchronous context manager
        await bot_instance.start(settings.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    if not settings.DISCORD_BOT_TOKEN:
        logger.critical("DISCORD_BOT_TOKEN is not set in the environment variables. Bot cannot start.")
    else:
        try:
            asyncio.run(main())
        except discord.LoginFailure:
            logger.critical("Failed to log in to Discord: Improper token has been passed or bot is not authorized.")
        except KeyboardInterrupt:
            logger.info("Bot shutdown requested via KeyboardInterrupt.")
        except Exception as e:
            logger.critical(f"An unexpected error occurred at the top level: {e}", exc_info=True)
        finally:
            logger.info("Bot process terminated.")