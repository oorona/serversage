# File: cogs/event_listeners_cog.py

import discord
from discord.ext import commands, tasks
import logging
import json
import os

logger = logging.getLogger(__name__)

class EventListenersCog(commands.Cog, name="EventListeners"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings
        self.llm_client = bot.llm_client
        self.verification_service = bot.verification_service
        
        # These will be populated in on_ready
        self.bot.categorized_server_roles: Dict[str, List[int]] = {} 
        self.bot.server_roles_map: Dict[int, str] = {} # role_id -> role_name

    async def _load_prompt(self, file_path: str) -> str:
        """Loads a prompt from a file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.error(f"Prompt file not found: {file_path}")
            return ""
        except Exception as e:
            logger.error(f"Error loading prompt file {file_path}: {e}", exc_info=True)
            return ""

    async def _load_categorized_roles_from_file(self) -> bool:
        """Loads categorized roles from the JSON file and updates bot attributes."""
        filepath = self.settings.CATEGORIZED_ROLES_FILE
        if not os.path.exists(filepath):
            logger.info(f"Categorized roles file not found: {filepath}. Will attempt to build.")
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                if not isinstance(loaded_data, dict): # Basic validation
                    logger.error(f"Categorized roles file {filepath} does not contain a valid JSON object.")
                    return False
                self.bot.categorized_server_roles = loaded_data
            logger.info(f"Successfully loaded categorized roles from {filepath}")
            await self._update_server_roles_map_from_categorized() # Update map after loading
            return True
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {filepath}. File might be corrupted.")
            self.bot.categorized_server_roles = {}
            return False
        except Exception as e:
            logger.error(f"Error loading categorized roles from {filepath}: {e}", exc_info=True)
            self.bot.categorized_server_roles = {}
            return False
            
    async def _update_server_roles_map_from_categorized(self):
        """
        Updates the bot.server_roles_map from bot.categorized_server_roles.
        This map (role_id -> role_name) is useful for constructing prompts for the LLM.
        """
        temp_map: Dict[int, str] = {}
        if not self.bot.guilds:
            logger.warning("Cannot update server_roles_map: Bot is not in any guilds yet.")
            return

        # Assuming single guild operation for now, or a clearly defined primary guild
        # If your bot operates on multiple guilds and role categorization is per-guild,
        # this logic would need to be adapted (e.g., store categorized roles per guild_id).
        primary_guild = self.bot.guilds[0] 
            
        for category_name, role_ids_in_category in self.bot.categorized_server_roles.items():
            if not isinstance(role_ids_in_category, list):
                logger.warning(f"Category '{category_name}' in categorized roles does not contain a list of IDs.")
                continue
            for role_id in role_ids_in_category:
                if not isinstance(role_id, int):
                    logger.warning(f"Invalid role ID '{role_id}' found in category '{category_name}'. Skipping.")
                    continue
                role = primary_guild.get_role(role_id)
                if role:
                    temp_map[role.id] = role.name
                else:
                    logger.warning(f"Role ID {role_id} from category '{category_name}' (categorized_roles.json) not found in server {primary_guild.name}")
        
        self.bot.server_roles_map = temp_map
        logger.info(f"Server roles map updated with {len(self.bot.server_roles_map)} roles.")


    async def _save_categorized_roles_to_file(self):
        """Saves the current bot.categorized_server_roles to the JSON file."""
        filepath = self.settings.CATEGORIZED_ROLES_FILE
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True) # Ensure data directory exists
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.bot.categorized_server_roles, f, indent=4)
            logger.info(f"Successfully saved categorized roles to {filepath}")
            await self._update_server_roles_map_from_categorized() # Update map after saving
        except Exception as e:
            logger.error(f"Error saving categorized roles to {filepath}: {e}", exc_info=True)

    async def perform_role_categorization(self, guild: discord.Guild, force_rebuild: bool = False):
        """
        Fetches roles, calls LLM to categorize, and saves them.
        If force_rebuild is False, it will try to load from file first unless
        REBUILD_ROLE_CATEGORIES_ON_STARTUP is true.
        """
        logger.info(f"Starting role categorization for guild: {guild.name}. Force rebuild: {force_rebuild}")
        
        # Check if we need to load or rebuild
        should_rebuild = force_rebuild or self.settings.REBUILD_ROLE_CATEGORIES_ON_STARTUP
        loaded_from_file = False
        if not should_rebuild:
            loaded_from_file = await self._load_categorized_roles_from_file()

        if should_rebuild or not loaded_from_file:
            if should_rebuild:
                logger.info(f"Forcing rebuild of role categories for guild: {guild.name}")
            else: # not loaded_from_file implies it's the first run or file was missing/corrupt
                logger.info(f"Categorized roles file not loaded. Proceeding with LLM categorization for guild: {guild.name}")

            roles_to_categorize_data = []
            for role in guild.roles:
                if not role.is_default() and not role.managed and not role.is_bot_managed() and not role.is_integration() and not role.is_premium_subscriber():
                    roles_to_categorize_data.append({"id": role.id, "name": role.name})
            
            if not roles_to_categorize_data:
                logger.info("No user-manageable roles suitable for categorization found.")
                self.bot.categorized_server_roles = {} # Clear it if no roles
                await self._save_categorized_roles_to_file()
                return

            prompt_template = await self._load_prompt(self.settings.PROMPT_PATH_ROLE_CATEGORIZATION_SYSTEM)
            if not prompt_template:
                logger.error("Role categorization prompt is empty or failed to load. Aborting categorization.")
                if not loaded_from_file: # If we absolutely have no data
                    self.bot.categorized_server_roles = {}
                    await self._save_categorized_roles_to_file()
                return # Keep existing data if prompt fails but data was loaded

            categorized_roles = await self.llm_client.categorize_server_roles(
                roles_data=roles_to_categorize_data,
                categorization_prompt=prompt_template
            )
            
            if categorized_roles: # If LLM returned something valid (even empty dict if no roles fit cats)
                self.bot.categorized_server_roles = categorized_roles
            else: 
                logger.warning("LLM role categorization returned no data or failed. Existing categorization (if any) will be kept unless it was a forced rebuild from empty.")
                if not loaded_from_file and not self.bot.categorized_server_roles: # If no prior data and LLM fails
                    self.bot.categorized_server_roles = {} # Ensure it's an empty dict
            
            await self._save_categorized_roles_to_file() # This also updates the map
        else:
            logger.info("Using existing categorized roles loaded from file.")
        
        logger.info(f"Role categorization complete. Categorized roles: {len(self.bot.categorized_server_roles)} categories. Roles map: {len(self.bot.server_roles_map)} roles.")


    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the bot is fully ready and connected."""
        logger.info(f"{self.bot.user.name} is ready. Initializing roles...")
        
        data_dir = os.path.dirname(self.settings.CATEGORIZED_ROLES_FILE)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            logger.info(f"Created data directory: {data_dir}")

        if self.bot.guilds:
            primary_guild = self.bot.guilds[0] # Assuming single guild or primary guild focus
            await self.perform_role_categorization(primary_guild, force_rebuild=self.settings.REBUILD_ROLE_CATEGORIES_ON_STARTUP)
        else:
            logger.warning("Bot is not in any guilds. Cannot perform initial role categorization on_ready.")
        
        logger.info(f"Bot categorized_server_roles initialized with {len(self.bot.categorized_server_roles)} categories.")
        logger.info(f"Bot server_roles_map initialized with {len(self.bot.server_roles_map)} mapped roles.")


    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Called when a new member joins the server."""
        if member.bot: # Ignore other bots
            return
            
        logger.info(f"New member joined: {member.name} (ID: {member.id}) in guild {member.guild.name}")

        # 1. Start verification process via DM
        if self.verification_service:
            # Ensure role data is available before starting verification
            if not self.bot.categorized_server_roles or not self.bot.server_roles_map:
                logger.warning(f"Role categorization data not yet available. Verification for {member.name} might be impacted.")
                # Optionally, try to trigger a quick categorization if it failed on_ready for some reason
                # await self.perform_role_categorization(member.guild, force_rebuild=True)
                # Or, queue the member for verification once roles are ready.
                # For now, we'll proceed, and the verification flow should handle missing role data gracefully.

            await self.verification_service.start_verification_process(member)
        else:
            logger.error("VerificationFlowService not available in EventListenersCog for on_member_join.")

        # 2. Send LLM-generated welcome message to a channel
        if self.settings.WELCOME_CHANNEL_ID and self.llm_client:
            welcome_channel = member.guild.get_channel(self.settings.WELCOME_CHANNEL_ID)
            if welcome_channel and isinstance(welcome_channel, discord.TextChannel):
                prompt_template = await self._load_prompt(self.settings.PROMPT_PATH_CHANNEL_WELCOME_SYSTEM_TEMPLATE)
                if prompt_template:
                    welcome_message_content = await self.llm_client.generate_welcome_message(
                        member_name=member.display_name,
                        server_name=member.guild.name,
                        member_id=member.id,
                        welcome_prompt_template_str=prompt_template
                    )
                    try:
                        await welcome_channel.send(welcome_message_content)
                        logger.info(f"Sent LLM welcome message for {member.name} to #{welcome_channel.name}")
                    except discord.Forbidden:
                        logger.error(f"Missing permissions to send message to welcome channel #{welcome_channel.name}")
                    except Exception as e:
                        logger.error(f"Failed to send welcome message: {e}", exc_info=True)
                else:
                    logger.error("Welcome message prompt is empty or failed to load.")
            else:
                logger.warning(f"Welcome channel ID {self.settings.WELCOME_CHANNEL_ID} not found or not a text channel.")
        elif not self.settings.WELCOME_CHANNEL_ID:
            logger.info("Welcome channel ID not configured. Skipping welcome message.")


async def setup(bot: commands.Bot):
    await bot.add_cog(EventListenersCog(bot))