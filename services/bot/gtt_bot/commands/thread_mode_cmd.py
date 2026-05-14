import logging

import discord
from discord import app_commands

from gtt_bot.discord_utils.permissions import is_allowed_guild
from gtt_bot.discord_utils.thread_mode import set_thread_mode

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="thread-mode", description="Toggle whether GTT Bot replies in threads or inline")
    @app_commands.describe(enabled="Turn thread mode on or off")
    @app_commands.choices(enabled=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def thread_mode(interaction: discord.Interaction, enabled: str):
        if not is_allowed_guild(interaction.guild_id):
            await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not any(
            r.name == "GTT Team" for r in interaction.user.roles
        ):
            await interaction.response.send_message("This command is restricted to GTT Team.", ephemeral=True)
            return
        state = enabled == "on"
        set_thread_mode(interaction.guild_id, state)
        status = "on — bot will reply in threads" if state else "off — bot will reply inline"
        await interaction.response.send_message(f"Thread mode **{status}**.", ephemeral=True)
        log.info("Thread mode set to %s for guild %s by %s", state, interaction.guild_id, interaction.user)
