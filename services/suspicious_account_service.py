import asyncio
import logging
import os
from typing import List, Optional
import discord
from discord.ext import tasks

logger = logging.getLogger(__name__)

class SuspiciousAccountService:
    def __init__(self, bot: discord.Client, llm_client, settings):
        self.bot = bot
        self.llm_client = llm_client
        self.settings = settings
        # Background task will be managed via discord tasks
        self.cleanup_task = None

    async def start(self):
        # Start the periodic cleanup task
        if self.cleanup_task is None:
            interval_hours = getattr(self.settings, 'SUSPICIOUS_CHECK_INTERVAL_HOURS', 24)
            self.cleanup_task = tasks.loop(hours=interval_hours)(self._periodic_cleanup)
            self.cleanup_task.start()
            logger.info("SuspiciousAccountService: periodic cleanup started.")

    async def stop(self):
        if self.cleanup_task and self.cleanup_task.is_running():
            self.cleanup_task.cancel()
            logger.info("SuspiciousAccountService: periodic cleanup stopped.")

    async def analyze_and_mark(self, guild: discord.Guild, member: discord.Member, user_messages: List[str], analysis_prompt_template: str):
        """Run LLM analysis on user messages and mark with suspicious role if flagged."""
        try:
            messages_text = "\n".join(user_messages)
            # Load template content if a file path was provided
            template_content = analysis_prompt_template
            try:
                if isinstance(analysis_prompt_template, str) and os.path.exists(analysis_prompt_template):
                    with open(analysis_prompt_template, 'r', encoding='utf-8') as f:
                        template_content = f.read()
            except Exception as e:
                logger.warning(f"SuspiciousAccountService: Could not read analysis prompt file {analysis_prompt_template}: {e}")

            # Log input size and which prompt template will be used
            try:
                logger.info(f"SuspiciousAccountService: analyze_and_mark for {member} -> {len(user_messages)} messages, total_chars={len(messages_text)}; using_template_len={len(template_content) if template_content else 0}")
            except Exception:
                pass

            if not messages_text.strip():
                logger.debug(f"SuspiciousAccountService: No user messages to analyze for member {member}.")

            response = await self.llm_client.classify_user_for_suspicion(messages_text, template_content, max_response_tokens=getattr(self.settings, 'LLM_MAX_RESPONSE_TOKENS', None))
            if not response:
                logger.info(f"SuspiciousAccountService: No response from LLM for {member.id}")
                return None

            is_suspicious = bool(response.get('is_suspicious'))
            reason = response.get('reason', '')

            if is_suspicious and getattr(self.settings, 'SUSPICIOUS_ROLE_ID', None):
                role = guild.get_role(self.settings.SUSPICIOUS_ROLE_ID)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Marked suspicious by LLM: {reason[:200]}")
                        logger.info(f"Marked member {member} as suspicious and added role {role.name}.")
                    except Exception as e:
                        logger.error(f"Failed to add suspicious role to {member}: {e}", exc_info=True)

                # Send notification to admin channel
                if getattr(self.settings, 'NOTIFICATION_CHANNEL_ID', None):
                    channel = guild.get_channel(self.settings.NOTIFICATION_CHANNEL_ID)
                    if channel and isinstance(channel, discord.TextChannel):
                        try:
                            # Build an embed consistent with other notifications
                            embed = discord.Embed(
                                title="Suspicious account detected",
                                description=f"A new account was flagged by the automated analysis.",
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow()
                            )
                            embed.add_field(name="Member", value=f"{member.mention}", inline=True)
                            embed.add_field(name="Member ID", value=str(member.id), inline=True)
                            embed.add_field(name="Reason", value=(reason[:500] or "No reason provided"), inline=False)
                            # Optionally include join time if available
                            try:
                                if member.joined_at:
                                    embed.add_field(name="Joined at", value=str(member.joined_at), inline=True)
                            except Exception:
                                pass

                            await channel.send(embed=embed)
                        except Exception as e:
                            logger.error(f"Failed to send suspicious account notification: {e}", exc_info=True)
            return response
        except Exception as e:
            logger.error(f"Error analyzing user for suspicion: {e}", exc_info=True)
            return None

    async def _periodic_cleanup(self):
        """Runs periodically and removes suspicious role from members who have aged past retention days."""
        try:
            retention_days = getattr(self.settings, 'SUSPICIOUS_ROLE_RETENTION_DAYS', 7)
            suspicious_role_id = getattr(self.settings, 'SUSPICIOUS_ROLE_ID', None)
            if not suspicious_role_id:
                logger.debug("SuspiciousAccountService: No SUSPICIOUS_ROLE_ID configured; skipping cleanup.")
                return

            for guild in self.bot.guilds:
                role = guild.get_role(suspicious_role_id)
                if not role:
                    continue
                now = discord.utils.utcnow()
                for member in role.members:
                    joined = member.joined_at
                    if not joined:
                        continue
                    age_days = (now - joined).days
                    if age_days >= retention_days:
                        try:
                            await member.remove_roles(role, reason="Suspicious role retention expired; account acted fine.")
                            logger.info(f"Removed suspicious role from {member} in {guild.name} after {age_days} days.")
                        except Exception as e:
                            logger.error(f"Failed to remove suspicious role from {member}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Periodic cleanup error: {e}", exc_info=True)