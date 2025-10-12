# File: cogs/user_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
from pathlib import Path
from typing import Dict, List

DEFAULT_INTERACTION_TIMEOUT = 300  # seconds

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
        # Be defensive: interaction tokens can expire or already be acknowledged which raises NotFound.
        deferred_successfully = False
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            deferred_successfully = True
        except Exception as e:
            logger.warning(f"Could not defer interaction for /assign-roles: {e}. Falling back to DM-only flow.")
            deferred_successfully = False
        # --- MODIFICATION END ---

        if not interaction.guild:
            # Use followup because we have already deferred
            await interaction.followup.send("This command can only be used within a server.", ephemeral=True)
            return

        if interaction.user.bot:
            # Use followup
            await interaction.followup.send("Bots cannot use this command.", ephemeral=True)
            return

        # If the user already has the verified role, present the ephemeral interactive role selector
        user_roles_ids = {r.id for r in interaction.user.roles}
        try:
            verified_role_id = int(self.settings.VERIFIED_ROLE_ID)
        except Exception:
            verified_role_id = None

        if verified_role_id and verified_role_id in user_roles_ids:
            # Launch ephemeral multi-step UI to let the verified user replace their category roles
            try:
                view = VerifiedRoleSelectorView(self.bot, interaction.user, self.settings)
                # Populate the first select with live guild role options before sending
                try:
                    await view._populate_current_select(interaction.guild)
                except Exception:
                    logger.debug("Could not pre-populate select options before sending view; will attempt to populate on interaction.")
                sent = await interaction.followup.send("Select roles to add/remove per category. You can navigate with Next/Back.", ephemeral=True, view=view)
                # store the message for timeout handling
                try:
                    view.message = sent
                except Exception:
                    pass
                return
            except Exception as e:
                logger.error(f"Failed to launch VerifiedRoleSelectorView: {e}", exc_info=True)
                # For verified users, do NOT fall back to the DM verification flow. Inform the user ephemerally and return.
                try:
                    await interaction.followup.send("Sorry — could not open the interactive role selector. Please contact an administrator.", ephemeral=True)
                except Exception:
                    logger.debug("Failed to send fallback ephemeral error to user after view launch failure.")
                return

        if self.verification_service:
            # If we successfully deferred above, pass the interaction so the service can use followups.
            # If deferral failed, call without interaction so the service uses DMs only and avoids followup errors.
            try:
                if deferred_successfully:
                    await self.verification_service.start_verification_process(interaction.user, interaction)
                else:
                    await self.verification_service.start_verification_process(interaction.user, None)
            except Exception as e:
                logger.error(f"Error starting verification service from /assign-roles: {e}", exc_info=True)
        else:
            logger.error("Verification service not available for '/assign-roles'.")
            # Use followup
            await interaction.followup.send(
                "Sorry, the verification service is currently unavailable. Please try again later or contact an administrator.",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(UserCommandsCog(bot))


class VerifiedRoleSelectorView(discord.ui.View):
    """Multi-step ephemeral UI for verified users to pick roles per category and apply them."""
    def __init__(self, bot: commands.Bot, user: discord.Member, settings):
        super().__init__(timeout=DEFAULT_INTERACTION_TIMEOUT)
        self.bot = bot
        self.user = user
        self.settings = settings
        # Load categories live from data file
        self.categorized_roles = self._load_categorized_roles()
        self.categories = list(self.categorized_roles.keys())
        # Keep selections per category (role IDs)
        self.selections: Dict[str, List[int]] = {cat: [] for cat in self.categories}
        self.current_index = 0
        self.message = None
        # Build initial select for first category
        self._refresh_items_for_current()

    def _load_categorized_roles(self) -> Dict[str, List[int]]:
        path = Path('data/categorized_roles.json')
        try:
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                # data expected: category -> list of role ids
                return {k: list(map(int, v)) for k, v in data.items()}
        except Exception:
            return {}

    def _role_options_for_category(self, guild: discord.Guild, category: str) -> List[discord.SelectOption]:
        options: List[discord.SelectOption] = []
        role_ids = self.categorized_roles.get(category, [])
        for rid in role_ids:
            role = guild.get_role(int(rid))
            if role:
                options.append(discord.SelectOption(label=role.name[:100], value=str(role.id)))
        return options

    def _refresh_items_for_current(self):
        # Remove existing dynamic children
        for item in list(self.children):
            if isinstance(item, discord.ui.Select) or isinstance(item, discord.ui.Button):
                self.remove_item(item)

        # Add select for the current category
        if not self.categories:
            return
        category = self.categories[self.current_index]
        # create select with conservative default; we'll populate options and adjust max_values later
        select = discord.ui.Select(placeholder=f"Select roles for {category}", min_values=0, max_values=1, options=[])
        # options populated later when we have guild context
        select.callback = self._on_select
        self.add_item(select)

        # Navigation buttons
        btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        btn_next = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary)
        btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        btn_finish = discord.ui.Button(label="Finish", style=discord.ButtonStyle.success)

        btn_back.callback = self._on_back
        btn_next.callback = self._on_next
        btn_cancel.callback = self._on_cancel
        btn_finish.callback = self._on_finish

        # Back disabled on first page
        btn_back.disabled = self.current_index == 0
        # Finish only shown on last page
        if self.current_index < len(self.categories) - 1:
            btn_finish.disabled = True

        self.add_item(btn_back)
        self.add_item(btn_next)
        self.add_item(btn_finish)
        self.add_item(btn_cancel)

    async def _on_select(self, interaction: discord.Interaction):
        # Save selections for this category
        values = [int(v) for v in interaction.data.get('values', [])]
        category = self.categories[self.current_index]
        self.selections[category] = values
        await interaction.response.defer(ephemeral=True)

    async def _on_next(self, interaction: discord.Interaction):
        # Move forward
        if self.current_index < len(self.categories) - 1:
            self.current_index += 1
            # refresh options with current guild
            guild = interaction.guild
            await self._populate_current_select(guild)
            await interaction.response.edit_message(content=f"Select roles for {self.categories[self.current_index]}", view=self)
        else:
            await interaction.response.defer(ephemeral=True)

    async def _on_back(self, interaction: discord.Interaction):
        if self.current_index > 0:
            self.current_index -= 1
            guild = interaction.guild
            await self._populate_current_select(guild)
            await interaction.response.edit_message(content=f"Select roles for {self.categories[self.current_index]}", view=self)
        else:
            await interaction.response.defer(ephemeral=True)

    async def _on_cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Role selection canceled.", view=None)
        self.stop()

    async def _on_finish(self, interaction: discord.Interaction):
        # Show summary and ask for confirmation
        summary_lines = []
        guild = interaction.guild
        for cat, ids in self.selections.items():
            names = [guild.get_role(rid).name for rid in ids if guild.get_role(rid)]
            if names:
                summary_lines.append(f"**{cat}**: {', '.join(names)}")
        summary = "\n".join(summary_lines) or "No roles selected."
        # Confirmation view
        confirm_view = discord.ui.View(timeout=120)
        btn_apply = discord.ui.Button(label="Apply", style=discord.ButtonStyle.success)
        btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)

        async def apply_cb(i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            await self._apply_selections(i)
            confirm_view.stop()

        async def cancel_cb(i: discord.Interaction):
            await i.response.edit_message(content="Role update canceled.", view=None)
            confirm_view.stop()

        btn_apply.callback = apply_cb
        btn_cancel.callback = cancel_cb
        confirm_view.add_item(btn_apply)
        confirm_view.add_item(btn_cancel)

        await interaction.response.edit_message(content=f"Resumen de selección:\n{summary}", view=confirm_view)

    async def _populate_current_select(self, guild: discord.Guild):
        # Rebuild categories filtered to those that actually have roles in this guild.
        filtered = []
        for cat in list(self.categorized_roles.keys()):
            role_ids = self.categorized_roles.get(cat, [])
            has_live = any(guild.get_role(int(rid)) for rid in role_ids)
            if has_live:
                filtered.append(cat)

        if not filtered:
            # No categories with live roles. Rebuild the view and show a disabled placeholder select.
            self.categories = []
            self.selections = {}
            self.current_index = 0
            self._refresh_items_for_current()
            for child in self.children:
                if isinstance(child, discord.ui.Select):
                    child.options = []
                    child.disabled = True
                    child.placeholder = "No categorized roles are available in this server."
            return

        # Replace categories with only those that have roles in this guild
        # Preserve any existing selections for categories that remain
        old_selections = self.selections
        self.categories = filtered
        self.selections = {cat: old_selections.get(cat, []) for cat in self.categories}
        # Ensure current_index is within bounds
        if self.current_index >= len(self.categories):
            self.current_index = 0

        # Rebuild view items for the (filtered) current categories
        self._refresh_items_for_current()

        # Now populate the select for the current category
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                options = self._role_options_for_category(guild, self.categories[self.current_index])
                # replace options
                child.options = options
                # adjust max_values to not exceed available options (Discord requires max_values <= len(options))
                try:
                    child.max_values = min(25, len(options)) if len(options) > 0 else 1
                except Exception:
                    pass
                # disable if no options (shouldn't happen since we filtered), but keep safe
                child.disabled = len(options) == 0
                if len(options) == 0:
                    child.placeholder = f"No roles available in {self.categories[self.current_index]}"
                # set already selected values by marking SelectOption.default=True
                selected_ids = {str(rid) for rid in self.selections.get(self.categories[self.current_index], [])}
                for opt in child.options:
                    opt.default = opt.value in selected_ids

    async def on_timeout(self):
        # Edit message to notify user
        try:
            if self.message:
                await self.message.edit(content="Role selection timed out.", view=None)
        except Exception:
            pass

    async def _apply_selections(self, interaction: discord.Interaction):
        # Replace roles per category: remove previous category roles, add selected ones
        guild = interaction.guild
        member = guild.get_member(self.user.id)
        if not member:
            await interaction.followup.send("Could not find your member object in the guild.", ephemeral=True)
            return

        # Track roles that failed to apply
        failed_assign = []

        # Build a mapping of category -> role ids available on guild at this moment
        live_category_map = {}
        for cat, ids in self.categorized_roles.items():
            live_category_map[cat] = [rid for rid in ids if guild.get_role(int(rid))]

        # For each category, remove all live roles in that category from the member, then add selected
        for cat, live_ids in live_category_map.items():
            # remove existing roles in that category
            for rid in live_ids:
                role = guild.get_role(int(rid))
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="User self-service role update")
                    except Exception:
                        failed_assign.append((cat, rid))
            # add selected for this category
            selected_ids = self.selections.get(cat, [])
            for rid in selected_ids:
                role = guild.get_role(int(rid))
                if role:
                    try:
                        await member.add_roles(role, reason="User self-service role update")
                    except Exception:
                        failed_assign.append((cat, rid))

        # Notify the user and admins if necessary
        if failed_assign:
            # inform user briefly
            await interaction.followup.send("Some roles could not be assigned due to permission or hierarchy issues. Admins have been notified.", ephemeral=True)
            # prepare admin embed like other notifications
            admin_channel = None
            try:
                admin_channel = guild.get_channel(self.settings.NOTIFICATION_CHANNEL_ID)
            except Exception:
                admin_channel = None
            if admin_channel and hasattr(admin_channel, 'send'):
                embed = discord.Embed(title="Role assignment problems",
                                      description=f"User {member.mention} tried to update roles but some roles could not be changed.", color=0xE74C3C)
                for cat, rid in failed_assign:
                    role_obj = guild.get_role(int(rid))
                    embed.add_field(name=cat, value=role_obj.name if role_obj else str(rid), inline=False)
                await admin_channel.send(embed=embed)
        else:
            await interaction.followup.send("Your roles were updated successfully.", ephemeral=True)

        self.stop()