# File: bot.py

import discord
from discord.ext import commands
import logging
import os
import httpx # For the shared HTTP session

# Assuming settings will be imported from config and passed or accessed globally
from config import settings

logger = logging.getLogger(__name__)

class VerificationBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings # Make settings easily accessible
        
        # Initialize shared resources here, to be attached before cogs load
        # This http_session will be created in setup_hook before LLMClient is initialized
        self.http_session: Optional[httpx.AsyncClient] = None
        self.llm_client = None # Will be initialized in setup_hook
        self.verification_service = None # Will be initialized in setup_hook

        # These will be populated by EventListenersCog on_ready
        self.categorized_server_roles: Dict[str, List[int]] = {} 
        self.server_roles_map: Dict[int, str] = {} # role_id -> role_name

    async def setup_hook(self):
        """
        This is called when the bot is loading its extensions (cogs).
        It's a good place to load cogs or perform other async setup.
        """
        logger.info("Running setup_hook...")

        # Initialize HTTP client for LLM interactions
        self.http_session = httpx.AsyncClient(timeout=30.0) # Adjust timeout as needed
        logger.info("HTTP session initialized.")

        # Initialize services and attach them to the bot
        # Ensure these imports are correct based on your project structure
        from llm_integration.llm_client import LLMClient # Moved import here
        self.llm_client = LLMClient(
            api_url=str(self.settings.LLM_API_URL),
            api_token=self.settings.LLM_API_TOKEN,
            model_name=self.settings.LLM_MODEL_NAME,
            http_session=self.http_session # Pass the created session
        )
        logger.info("LLMClient initialized.")

        from services.verification_flow_service import VerificationFlowService # Moved import here
        self.verification_service = VerificationFlowService(
            bot=self, 
            llm_client=self.llm_client, 
            settings=self.settings
        )
        logger.info("VerificationFlowService initialized.")
        
        # Load cogs
        cog_dir = "cogs"
        logger.info(f"Attempting to load extensions from ./{cog_dir}")
        for filename in os.listdir(f"./{cog_dir}"): # Use relative path for robustness
            if filename.endswith("_cog.py"): # Standardized cog naming
                cog_name = f"{cog_dir}.{filename[:-3]}"
                try:
                    await self.load_extension(cog_name)
                    logger.info(f"Successfully loaded extension: {cog_name}")
                except commands.ExtensionAlreadyLoaded:
                    logger.warning(f"Extension already loaded: {cog_name}")
                except commands.ExtensionNotFound:
                    logger.error(f"Extension not found: {cog_name}")
                except commands.NoEntryPointError:
                    logger.error(f"Extension {cog_name} has no setup function.")
                except Exception as e:
                    logger.error(f"Failed to load extension {cog_name}: {e}", exc_info=True)
        logger.info("Cog loading process complete.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        logger.info(f"discord.py version: {discord.__version__}")
        logger.info("Bot is ready and online!")
        
        # Synchronize application commands (slash commands)
        try:
            # For global sync (can take up to an hour to propagate for new commands/changes):
            synced = await self.tree.sync()
            # To sync to a specific guild for faster updates during development:
            # GUILD_ID = discord.Object(id=YOUR_TEST_GUILD_ID) # Replace with your guild ID
            # self.tree.copy_global_to(guild=GUILD_ID)
            # synced = await self.tree.sync(guild=GUILD_ID)
            logger.info(f"Synced {len(synced)} application commands.")
        except Exception as e:
            logger.error(f"Failed to sync application commands: {e}", exc_info=True)

    async def on_shutdown(self):
        """
        Clean up resources on shutdown.
        This method is not automatically called by discord.py on bot.close() or bot.run() ending.
        You would typically call this manually if handling signals or specific shutdown sequences.
        The `async with bot:` context manager in `main.py` will call `bot.close()`,
        which handles some cleanup including closing the HTTP session if `self.http_session.is_closed` is false.
        """
        if self.http_session and not self.http_session.is_closed:
            await self.http_session.aclose()
            logger.info("HTTP session closed during shutdown.")

    async def close(self):
        """Override close to include custom shutdown logic."""
        logger.info("Bot close called. Cleaning up...")
        await self.on_shutdown() # Call our custom shutdown logic
        await super().close()    # Call the parent class's close method
        logger.info("Bot has been closed.")