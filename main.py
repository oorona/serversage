# File: main.py

import asyncio
import discord
from discord.ext import commands
import logging
import httpx # Added for httpx.AsyncClient

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
from llm_integration.llm_client import LLMClient # Import LLMClient
from services.verification_flow_service import VerificationFlowService # Import VerificationFlowService


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
    # The VerificationBot instance will load settings from the imported 'settings' object
    bot_instance = VerificationBot(
        command_prefix=commands.when_mentioned_or("!verify "), # Fallback, primarily slash commands
        intents=intents,
        help_command=None # Disable default help command
    )

    # Setup HTTPX AsyncClient for LLMClient
    http_session = httpx.AsyncClient(timeout=30.0)

    llm_client = LLMClient(
        api_url=str(settings.LLM_API_URL), # Pydantic HttpUrl to string
        api_token=settings.LLM_API_TOKEN,
        model_name=settings.LLM_MODEL_NAME,
        http_session=http_session
    )

    # Initialize VerificationFlowService
    verification_service = VerificationFlowService(
        bot=bot_instance, # Pass the bot instance
        llm_client=llm_client,
        settings=settings
    )

    # Attach services and settings to the bot instance
    bot_instance.verification_service = verification_service
    bot_instance.llm_client = llm_client
    bot_instance.settings = settings

    # Load cogs
    logger.info("Loading cogs...")
    try:
        await bot_instance.load_extension("cogs.admin_commands_cog")
        await bot_instance.load_extension("cogs.user_commands_cog")
        await bot_instance.load_extension("cogs.event_listeners_cog")
        logger.info("All cogs loaded successfully.")
    except Exception as e:
        logger.exception(f"Failed to load cogs: {e}")

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
    finally:
        logger.info("Bot is shutting down. Closing HTTP session.")
        await http_session.aclose() # Ensure HTTPX session is closed gracefully


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