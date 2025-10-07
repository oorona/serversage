# File: cogs/user_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

class UserCommandsCog(commands.Cog, name="UserCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings
        self.verification_service = bot.verification_service

    @app_commands.command(
        name="assign-roles",
        description="Start or restart the role verification process for yourself."
    )
    async def assign_roles(self, interaction: discord.Interaction):
        """
        Allows a user to self-initiate or re-attempt the DM verification process.
        """
        logger.info(f"User command '/assign-roles' used by {interaction.user.name} (ID: {interaction.user.id})")
        
        # Acknowledge the interaction immediately so it doesn't time out.
        await interaction.response.defer(ephemeral=True, thinking=True)
        # --- MODIFICATION END ---

        if not interaction.guild:
            # Use followup because we have already deferred
            await interaction.followup.send("This command can only be used within a server.", ephemeral=True)
            return

        if interaction.user.bot:
            # Use followup
            await interaction.followup.send("Bots cannot use this command.", ephemeral=True)
            return

        if self.verification_service:
            # The service will now also use followup messages.
            await self.verification_service.start_verification_process(interaction.user, interaction)
        else:
            logger.error("Verification service not available for '/assign-roles'.")
            # Use followup
            await interaction.followup.send(
                "Sorry, the verification service is currently unavailable. Please try again later or contact an administrator.",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(UserCommandsCog(bot))