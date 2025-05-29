# File: cogs/user_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands # Required for slash commands
import logging

# Assuming VerificationFlowService is correctly imported or available on bot instance
# from ..services.verification_flow_service import VerificationFlowService
# from ..config import Settings # For type hinting if needed

logger = logging.getLogger(__name__)

class UserCommandsCog(commands.Cog, name="UserCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings # type: ignore # settings is attached in main.py
        self.verification_service = bot.verification_service # type: ignore

    @app_commands.command(
        name="assign-roles",
        description="Start or restart the role verification process for yourself."
    )
    async def assign_roles(self, interaction: discord.Interaction):
        """
        Allows a user to self-initiate or re-attempt the DM verification process.
        """
        logger.info(f"User command '/assign-roles' used by {interaction.user.name} (ID: {interaction.user.id})")

        if not interaction.guild:
            # This check is good practice, though DMs are the primary interaction point.
            # Slash commands can technically be invoked from DMs with the bot if the bot supports it,
            # but our verification context is per-guild.
            await interaction.response.send_message("This command can only be used within a server.", ephemeral=True)
            return

        if interaction.user.bot:
            await interaction.response.send_message("Bots cannot use this command.", ephemeral=True)
            return

        if self.verification_service:
            # The start_verification_process method now handles sending an ephemeral message
            # back to the interaction if one is provided.
            await self.verification_service.start_verification_process(interaction.user, interaction) # type: ignore
        else:
            logger.error("Verification service not available for '/assign-roles'.")
            await interaction.response.send_message(
                "Sorry, the verification service is currently unavailable. Please try again later or contact an administrator.",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    # Check if UserCommandsCog is already added, to prevent issues on reload
    # if bot.get_cog("UserCommands") is None:
    await bot.add_cog(UserCommandsCog(bot))
    # else:
    # logger.info("UserCommandsCog already loaded.")