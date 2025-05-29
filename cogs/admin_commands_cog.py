# File: cogs/admin_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands # Required for slash commands
import logging
import asyncio # For potential delays in batch processing

# Assuming VerificationFlowService is correctly imported or available on bot instance
# from ..services.verification_flow_service import VerificationFlowService 
# from ..config import Settings # For type hinting if needed

logger = logging.getLogger(__name__)

async def check_admin_roles(interaction: discord.Interaction) -> bool:
    """Checks if the user invoking the command has one of the configured admin roles."""
    # Access settings through the bot instance, which should be available in interaction.client
    bot_instance = interaction.client
    if not hasattr(bot_instance, 'settings') or not hasattr(bot_instance.settings, 'PARSED_ADMIN_ROLE_IDS'):
        logger.error("Admin role settings not found on bot instance. Denying admin command access.")
        return False

    admin_role_ids = bot_instance.settings.PARSED_ADMIN_ROLE_IDS
    if not admin_role_ids:
        logger.warning(f"No admin roles configured. Denying access for {interaction.user.name} to an admin command.")
        return False # No admin roles configured, so no one is an admin for the bot

    user_role_ids = {role.id for role in interaction.user.roles} # type: ignore
    
    is_admin = any(admin_id in user_role_ids for admin_id in admin_role_ids)
    if not is_admin:
        logger.warning(f"User {interaction.user.name} (ID: {interaction.user.id}) attempted to use an admin command without required role(s).")
    return is_admin

class AdminCommandsCog(commands.Cog, name="AdminCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings # type: ignore # settings is attached in main.py
        self.llm_client = bot.llm_client # type: ignore
        self.verification_service = bot.verification_service # type: ignore

    # Define the admin command group
    admin_group = app_commands.Group(
        name="admin", 
        description="Administrative commands for the verification bot."
        # default_permissions can be set here if needed, or rely on checks
    )

    @admin_group.command(name="verify-user", description="Manually starts the verification process for a specific member.")
    @app_commands.check(check_admin_roles)
    @app_commands.describe(member="The member to start verification for.")
    async def verify_user(self, interaction: discord.Interaction, member: discord.Member):
        logger.info(f"Admin command '/admin verify-user' used by {interaction.user.name} for {member.name}")
        
        if member.bot:
            await interaction.response.send_message(f"{member.mention} is a bot and cannot be verified.", ephemeral=True)
            return

        if self.verification_service:
            # The service's start_verification_process now handles ephemeral responses if interaction is passed
            await self.verification_service.start_verification_process(member, interaction)
            # No need for followup here if start_verification_process sends the initial response.
            # If it doesn't, then:
            # await interaction.response.send_message(f"Attempting to start verification for {member.mention}. They will receive a DM.", ephemeral=True)
        else:
            logger.error("Verification service not available for '/admin verify-user'.")
            await interaction.response.send_message("Error: Verification service is not available. Please contact bot support.", ephemeral=True)

    @admin_group.command(name="initiate-verification-batch", description="Initiates DM verification for a batch of unverified users.")
    @app_commands.check(check_admin_roles)
    @app_commands.describe(count="The maximum number of users to include in this batch (e.g., 10).")
    async def initiate_verification_batch(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 100]):
        logger.info(f"Admin command '/admin initiate-verification-batch' used by {interaction.user.name} for {count} users.")
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        if not self.verification_service:
            logger.error("Verification service not available for '/admin initiate-verification-batch'.")
            await interaction.followup.send("Error: Verification service is not available.", ephemeral=True)
            return

        unverified_role_id = self.settings.UNVERIFIED_ROLE_ID
        verified_role_id = self.settings.VERIFIED_ROLE_ID
        inprogress_role_id = self.settings.VERIFICATION_IN_PROGRESS_ROLE_ID

        unverified_role = interaction.guild.get_role(unverified_role_id)
        if not unverified_role:
            await interaction.followup.send(f"Error: The 'Unverified' role (ID: {unverified_role_id}) is not configured or found on this server.", ephemeral=True)
            return

        candidates = []
        for member in interaction.guild.members:
            if member.bot:
                continue
            
            member_role_ids = {role.id for role in member.roles}
            
            # Candidate if: has unverified_role AND does NOT have verified_role AND does NOT have inprogress_role
            # Or, if they simply don't have verified or inprogress, and might not even have unverified yet (e.g. very new setup)
            # For batch, let's primarily target those marked as 'unverified'.
            if unverified_role_id in member_role_ids and \
               verified_role_id not in member_role_ids and \
               inprogress_role_id not in member_role_ids:
                candidates.append(member)
            
            if len(candidates) >= count * 2: # Fetch a bit more to account for potential DM failures later if needed
                break
        
        if not candidates:
            await interaction.followup.send("No users found matching the criteria for a new verification batch (e.g., having the 'Unverified' role and not 'Verified' or 'In Progress').", ephemeral=True)
            return

        actual_batch = candidates[:count]
        processed_count = 0
        error_count = 0

        await interaction.followup.send(f"Starting verification process for {len(actual_batch)} users. This may take a moment. Users will receive DMs.", ephemeral=True)

        for member_to_verify in actual_batch:
            try:
                # We don't pass the interaction here as it's already responded to.
                # The start_verification_process will just send DMs.
                await self.verification_service.start_verification_process(member_to_verify)
                processed_count += 1
                # Optional: add a small delay to avoid hitting DM rate limits too quickly
                await asyncio.sleep(1) # 1-second delay between DMs
            except Exception as e:
                logger.error(f"Error starting verification for {member_to_verify.name} in batch: {e}", exc_info=True)
                error_count += 1
        
        # Send a final summary (optional, could be too noisy for large batches)
        # For now, the initial followup is the main feedback.
        logger.info(f"Batch verification complete. Attempted: {len(actual_batch)}. Successful starts: {processed_count}. Errors: {error_count}.")


    @admin_group.command(name="reset-stale-verifications", description="Resets users in 'verification in progress' or unprofiled to 'unverified'.")
    @app_commands.check(check_admin_roles)
    async def reset_stale_verifications(self, interaction: discord.Interaction):
        logger.info(f"Admin command '/admin reset-stale-verifications' used by {interaction.user.name}.")
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        inprogress_role_id = self.settings.VERIFICATION_IN_PROGRESS_ROLE_ID
        verified_role_id = self.settings.VERIFIED_ROLE_ID
        unverified_role_id = self.settings.UNVERIFIED_ROLE_ID

        inprogress_role = interaction.guild.get_role(inprogress_role_id)
        unverified_role = interaction.guild.get_role(unverified_role_id)

        if not unverified_role:
            await interaction.followup.send(f"Error: The 'Unverified' role (ID: {unverified_role_id}) is not configured or found. Cannot reset users.", ephemeral=True)
            return
        
        reset_count = 0
        users_to_reset_roles: List[discord.Member] = []

        for member in interaction.guild.members:
            if member.bot:
                continue

            member_role_ids = {role.id for role in member.roles}
            
            is_verified = verified_role_id in member_role_ids
            is_in_progress = inprogress_role_id in member_role_ids
            is_unverified = unverified_role_id in member_role_ids # For checking if unverified needs to be ADDED

            # Target 1: Users stuck in "in progress" (and not also verified)
            if is_in_progress and not is_verified:
                users_to_reset_roles.append(member)
            # Target 2: Users with no verification status at all (not verified, not unverified, not in_progress)
            elif not is_verified and not is_unverified and not is_in_progress:
                 users_to_reset_roles.append(member)

        if not users_to_reset_roles:
            await interaction.followup.send("No users found requiring a reset to 'unverified' status.", ephemeral=True)
            return

        for member_to_reset in users_to_reset_roles:
            roles_to_add = [unverified_role] if unverified_role else []
            roles_to_remove = [inprogress_role] if inprogress_role and inprogress_role in member_to_reset.roles else []
            
            try:
                if roles_to_remove:
                    await member_to_reset.remove_roles(*roles_to_remove, reason="Admin reset stale verification") # type: ignore
                if roles_to_add and not (unverified_role in member_to_reset.roles): # Add unverified only if not already present
                    await member_to_reset.add_roles(*roles_to_add, reason="Admin reset stale verification / Initial assignment") # type: ignore
                reset_count += 1
                logger.info(f"Reset user {member_to_reset.name} to unverified. Removed: {[r.name for r in roles_to_remove if r]}. Added: {[r.name for r in roles_to_add if r]}.")
            except discord.Forbidden:
                logger.error(f"Missing permissions to modify roles for {member_to_reset.name} during reset.")
            except discord.HTTPException as e:
                logger.error(f"HTTP error modifying roles for {member_to_reset.name} during reset: {e}")
            except Exception as e:
                logger.error(f"Unexpected error resetting user {member_to_reset.name}: {e}", exc_info=True)
        
        await interaction.followup.send(f"Successfully reset {reset_count} user(s) to 'unverified' status (or ensured they have it).", ephemeral=True)


    @admin_group.command(name="rebuild-role-categories", description="Manually rebuilds the LLM's categorization of server roles.")
    @app_commands.check(check_admin_roles)
    async def rebuild_role_categories(self, interaction: discord.Interaction):
        logger.info(f"Admin command '/admin rebuild-role-categories' used by {interaction.user.name}")
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        event_cog = self.bot.get_cog("EventListeners") # type: ignore # Bot should have this cog
        if event_cog and hasattr(event_cog, 'perform_role_categorization'):
            try:
                await event_cog.perform_role_categorization(interaction.guild, force_rebuild=True)
                await interaction.followup.send("Role categorization process has been initiated and forced to rebuild. Check logs for details.", ephemeral=True)
            except Exception as e:
                logger.error(f"Error during rebuild_role_categories command execution: {e}", exc_info=True)
                await interaction.followup.send(f"An error occurred while rebuilding role categories: {e}", ephemeral=True)
        else:
            logger.error("EventListenersCog or perform_role_categorization method not found for '/admin rebuild-role-categories'.")
            await interaction.followup.send("Error: Could not trigger role categorization. System component missing.", ephemeral=True)


async def setup(bot: commands.Bot):
    # Check if AdminCommandsCog is already added, to prevent issues on reload
    # if bot.get_cog("AdminCommands") is None:
    await bot.add_cog(AdminCommandsCog(bot))
    # else:
    #     logger.info("AdminCommandsCog already loaded.")