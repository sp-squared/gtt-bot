import logging
import time

import discord
from discord import app_commands

import gtt_bot.globals as G
from gtt_bot.config import (
    COLLECTION,
    COOLDOWN_ANTHROPIC,
    COOLDOWN_LOCAL,
    EMBED_MODEL,
    MAX_QUESTION_LENGTH,
    QDRANT_HOST,
    REQUIRED_ROLE,
)
from gtt_bot.discord_utils.permissions import is_allowed_guild
from gtt_bot.discord_utils.thread_mode import get_thread_mode

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="status", description="Show GTT Bot status and knowledge base info")
    async def status(interaction: discord.Interaction):
        if not is_allowed_guild(interaction.guild_id):
            await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            from qdrant_client import QdrantClient as QC
            qc = QC(url=QDRANT_HOST)
            info = qc.get_collection(COLLECTION)
            vector_count = info.points_count or 0
            uptime_seconds = int(time.time() - G._start_time)
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"
            thread_mode_str = "on" if get_thread_mode(interaction.guild_id) else "off"
            role_str = f"`{REQUIRED_ROLE}`" if REQUIRED_ROLE else "all members"
            msg = (
                f"**GTT Bot — Status**\n\n"
                f"`Knowledge base` {vector_count} chunks indexed\n"
                f"`Embed model` {EMBED_MODEL}\n"
                f"`LLM` claude-sonnet-4-5 (Anthropic API)\n"
                f"`API access` {role_str}\n"
                f"`Thread mode` {thread_mode_str}\n"
                f"`Uptime` {uptime_str}\n"
                f"`Cooldown` {COOLDOWN_ANTHROPIC}s (mention) · {COOLDOWN_LOCAL}s (search)\n"
                f"`Max question` {MAX_QUESTION_LENGTH} chars"
            )
            await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            log.exception("status command failed")
            await interaction.followup.send("Something went wrong fetching status.", ephemeral=True)