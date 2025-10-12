# File: cogs/admin_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
from typing import List

logger = logging.getLogger(__name__)

async def check_admin_roles(interaction: discord.Interaction) -> bool:
    """Checks if the user invoking the command has one of the configured admin roles."""
    bot_instance = interaction.client
    if not hasattr(bot_instance, 'settings') or not hasattr(bot_instance.settings, 'PARSED_ADMIN_ROLE_IDS'):
        logger.error("Admin role settings not found on bot instance. Denying admin command access.")
        return False

    admin_role_ids = bot_instance.settings.PARSED_ADMIN_ROLE_IDS
    if not admin_role_ids:
        logger.warning(f"No admin roles configured. Denying access for {interaction.user.name} to an admin command.")
        return False

    user_role_ids = {role.id for role in interaction.user.roles}
    
    is_admin = any(admin_id in user_role_ids for admin_id in admin_role_ids)
    if not is_admin:
        logger.warning(f"User {interaction.user.name} (ID: {interaction.user.id}) attempted to use an admin command without required role(s).")
    return is_admin

class AdminCommandsCog(commands.Cog, name="AdminCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings
        self.llm_client = bot.llm_client
        self.verification_service = bot.verification_service

    admin_group = app_commands.Group(
        name="admin", 
        description="Administrative commands for the verification bot."
    )

    @admin_group.command(name="verify-user", description="Manually starts the verification process for a specific member.")
    @app_commands.check(check_admin_roles)
    @app_commands.describe(member="The member to start verification for.")
    async def verify_user(self, interaction: discord.Interaction, member: discord.Member):
        logger.info(f"Admin command '/admin verify-user' used by {interaction.user.name} for {member.name}")
        
        # --- MODIFICATION START ---
        # Acknowledge the interaction immediately
        await interaction.response.defer(ephemeral=True, thinking=True)
        # --- MODIFICATION END ---
        
        if member.bot:
            # Use followup
            await interaction.followup.send(f"{member.mention} is a bot and cannot be verified.", ephemeral=True)
            return

        if self.verification_service:
            # The service will now use followup messages.
            await self.verification_service.start_verification_process(member, interaction)
        else:
            logger.error("Verification service not available for '/admin verify-user'.")
            # Use followup
            await interaction.followup.send("Error: Verification service is not available. Please contact bot support.", ephemeral=True)

    # ... (rest of the file remains the same) ...
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
            
            if unverified_role_id in member_role_ids and \
               verified_role_id not in member_role_ids and \
               inprogress_role_id not in member_role_ids:
                candidates.append(member)
            
            if len(candidates) >= count * 2:
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
                await self.verification_service.start_verification_process(member_to_verify)
                processed_count += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error starting verification for {member_to_verify.name} in batch: {e}", exc_info=True)
                error_count += 1
        
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
            is_unverified = unverified_role_id in member_role_ids

            if is_in_progress and not is_verified:
                users_to_reset_roles.append(member)
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
                    await member_to_reset.remove_roles(*roles_to_remove, reason="Admin reset stale verification")
                if roles_to_add and not (unverified_role in member_to_reset.roles):
                    await member_to_reset.add_roles(*roles_to_add, reason="Admin reset stale verification / Initial assignment")
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

        event_cog = self.bot.get_cog("EventListeners")
        if event_cog and hasattr(event_cog, 'perform_role_categorization'):
            try:
                await event_cog.perform_role_categorization(interaction.guild, force_rebuild=True)

                # Build a readable summary of the categorized roles for the ephemeral response
                categorized = getattr(self.bot, 'categorized_server_roles', {}) or {}
                lines = []
                for cat, ids in categorized.items():
                    names = []
                    for rid in ids:
                        try:
                            role = interaction.guild.get_role(int(rid))
                            if role:
                                names.append(role.name)
                        except Exception:
                            continue
                    if names:
                        lines.append(f"**{cat}** ({len(names)}): {', '.join(names)}")
                    else:
                        lines.append(f"**{cat}**: (no live roles)")

                summary_text = "\n".join(lines) or "No categorized roles found after rebuild."

                # Truncate ephemeral message if too long
                if len(summary_text) > 1800:
                    summary_text = summary_text[:1797] + "... (truncated)"

                await interaction.followup.send(content=f"Role categorization complete.\n\n{summary_text}", ephemeral=True)

                # Also send an embed notification to the configured notification channel, if available
                notif_channel_id = getattr(self.settings, 'NOTIFICATION_CHANNEL_ID', None)
                if notif_channel_id:
                    try:
                        admin_channel = interaction.guild.get_channel(int(notif_channel_id))
                    except Exception:
                        admin_channel = None

                    if admin_channel and hasattr(admin_channel, 'send'):
                        embed = discord.Embed(title="Role categories rebuilt", color=0x3498DB)
                        embed.description = f"Role categories were rebuilt by {interaction.user.mention}."

                        # Add fields per category, ensuring field value <= 1024 chars
                        for cat, ids in categorized.items():
                            names = []
                            for rid in ids:
                                try:
                                    role = interaction.guild.get_role(int(rid))
                                    if role:
                                        names.append(role.name)
                                except Exception:
                                    continue
                            value = ", ".join(names) if names else "(no live roles)"
                            if len(value) > 1000:
                                value = value[:997] + "..."
                            embed.add_field(name=cat, value=value, inline=False)

                        try:
                            await admin_channel.send(embed=embed)
                        except Exception as e:
                            logger.error(f"Failed to send role categories embed to notification channel: {e}", exc_info=True)
                    else:
                        logger.warning(f"Notification channel ID {notif_channel_id} not found or not sendable in guild {interaction.guild.name}.")
                else:
                    logger.info("No NOTIFICATION_CHANNEL_ID configured; skipping admin embed notification.")
            except Exception as e:
                logger.error(f"Error during rebuild_role_categories command execution: {e}", exc_info=True)
                await interaction.followup.send(f"An error occurred while rebuilding role categories: {e}", ephemeral=True)
        else:
            logger.error("EventListenersCog or perform_role_categorization method not found for '/admin rebuild-role-categories'.")
            await interaction.followup.send("Error: Could not trigger role categorization. System component missing.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCommandsCog(bot))