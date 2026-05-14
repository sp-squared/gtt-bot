import logging

import discord
from discord import app_commands

import gtt_bot.globals as G

log = logging.getLogger("bot")


async def _resolve_starter_author(thread: discord.Thread, client: discord.Client) -> int | None:
    """Return the user ID of whoever triggered the bot-created thread, or None."""
    # Check in-memory registry first (covers both mention and knowledge-search threads)
    if thread.id in G.thread_owners:
        return G.thread_owners[thread.id]
    # Fallback: for @mention threads thread.id == parent message.id
    try:
        parent = client.get_channel(thread.parent_id) or await client.fetch_channel(thread.parent_id)
        msg = await parent.fetch_message(thread.id)
        return msg.author.id
    except Exception as exc:
        log.warning("archive-thread: could not resolve starter author for %s: %s", thread.name, exc)
        return None


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="archive-thread", description="Archive or purge this thread (owner or GTT Team only)")
    @app_commands.describe(delete="Delete all messages before archiving (default: off)")
    @app_commands.choices(delete=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def archive_thread(interaction: discord.Interaction, delete: str = "off"):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Run this command inside the thread you want to archive.", ephemeral=True
            )
            return

        thread = interaction.channel
        user = interaction.user

        is_gtt_team = isinstance(user, discord.Member) and any(
            r.name == "GTT Team" for r in user.roles
        )

        # Direct owner check
        is_owner = thread.owner_id == user.id

        # For bot-created threads the owner is the bot — check the starter message author
        if not is_owner:
            starter_author_id = await _resolve_starter_author(thread, interaction.client)
            is_owner = starter_author_id == user.id

        if not is_owner and not is_gtt_team:
            await interaction.response.send_message(
                "You can only archive threads you created.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        if delete == "on":
            log.info("archive-thread: deleting thread %s by %s", thread.name, user)
            try:
                await thread.delete()
            except discord.NotFound:
                pass
            await interaction.followup.send("Thread deleted.", ephemeral=True)
        else:
            closing = (
                "*This thread has been archived by a mod.*"
                if is_gtt_team and not is_owner
                else "*This thread has been archived.*"
            )
            await thread.send(closing)
            await thread.edit(archived=True, locked=True)
            log.info("archive-thread: %s archived by %s", thread.name, user)
            await interaction.followup.send("Thread archived.", ephemeral=True)
