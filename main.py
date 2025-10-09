# File: main.py

import asyncio
import discord
from discord.ext import commands
import logging

# Load settings first to ensure they are available globally if needed
# and to catch configuration errors early.
try:
    from config import settings
except SystemExit as e:
    logging.critical(f"Bot cannot start due to critical configuration errors: {e}")
    print(f"CRITICAL: Bot cannot start due to critical configuration errors: {e}")
    exit(1)
except ImportError:
    logging.critical("Failed to import settings from config.py. Ensure config.py exists and is valid.")
    print("CRITICAL: Failed to import settings from config.py. Ensure config.py exists and is valid.")
    exit(1)


from utils.logging_setup import setup_logging
from bot import VerificationBot # Import the bot class from bot.py


# Setup logging using the level from settings, enabling file logging
setup_logging(log_level=settings.LOG_LEVEL, log_to_file=True)

# Get the root logger AFTER setup
logger = logging.getLogger(__name__)

# Define Intents - these are passed to the Bot constructor
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True


async def main():
    """
    Initializes and runs the bot.
    The VerificationBot class now handles its own internal setup of services
    like the LLMClient and VerificationFlowService via its setup_hook.
    """
    bot_instance = VerificationBot(
        command_prefix=commands.when_mentioned_or("!verify "), # Fallback, primarily slash commands
        intents=intents,
        help_command=None # Disable default help command
    )

    # NOTE: The initialization of httpx, LLMClient, VerificationFlowService,
    # and the loading of cogs have been moved into the bot.py's `setup_hook`.
    # This is the correct place for this logic and resolves the TypeError you saw.
    # The bot now sets itself up internally when it starts.

    # Run the bot
    logger.info("Starting bot...")
    try:
        await bot_instance.start(settings.DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logger.critical("Failed to log in to Discord. Please check your DISCORD_BOT_TOKEN.")
    except discord.HTTPException as e:
        logger.critical(f"HTTP error during bot startup: {e}")
    except Exception as e:
        logger.critical(f"An unexpected error occurred during bot startup: {e}", exc_info=True)
    # The bot's own close() method will handle cleanup of resources like the HTTP session,
    # so the `finally` block that was here is no longer needed.

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