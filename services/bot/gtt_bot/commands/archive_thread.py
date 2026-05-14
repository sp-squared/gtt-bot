import logging

import discord
from discord import app_commands

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="archive-thread",
        description="Archive this thread (and optionally delete all content)",
    )
    @app_commands.describe(delete="Delete all thread messages and the thread itself (default: no)")
    @app_commands.choices(delete=[
        app_commands.Choice(name="yes", value="yes"),
        app_commands.Choice(name="no", value="no"),
    ])
    async def archive_thread(
        interaction: discord.Interaction,
        delete: str = "no",
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        if not any(r.name in ("GTT Team", "admin") for r in interaction.user.roles):
            await interaction.response.send_message("This command is restricted to GTT Team.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Run this command inside the thread you want to archive.", ephemeral=True
            )
            return

        thread = interaction.channel

        # Try to resolve who originally started this thread
        starter_author = None
        if thread.parent:
            try:
                starter = await thread.parent.fetch_message(thread.id)
                starter_author = starter.author
            except (discord.NotFound, discord.HTTPException) as e:
                log.warning("archive-thread: could not resolve starter author for %s: %s", thread.name, e)

        await interaction.response.defer(ephemeral=True)

        if delete == "yes":
            thread_name = thread.name
            try:
                await thread.delete()
                log.info(
                    "archive-thread: deleted '%s' (starter: %s) by %s",
                    thread_name,
                    starter_author,
                    interaction.user,
                )
                # The thread (and its webhook) are gone — send confirmation via DM instead.
                try:
                    dm = await interaction.user.create_dm()
                    await dm.send(
                        f"✅ Thread **{thread_name}** and all its messages have been deleted."
                    )
                except discord.Forbidden:
                    log.warning(
                        "archive-thread: could not DM deletion confirmation to %s (DMs closed)",
                        interaction.user,
                    )
            except discord.Forbidden:
                await interaction.followup.send("Missing permissions to delete this thread.", ephemeral=True)
            except Exception:
                log.exception("archive-thread: failed to delete '%s'", thread_name)
                await interaction.followup.send("Something went wrong deleting the thread.", ephemeral=True)
        else:
            try:
                await thread.edit(archived=True, locked=True)
                log.info(
                    "archive-thread: archived '%s' (starter: %s) by %s",
                    thread.name,
                    starter_author,
                    interaction.user,
                )
                await interaction.followup.send(
                    f"Thread **{thread.name}** has been archived and locked.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send("Missing permissions to archive this thread.", ephemeral=True)
            except Exception:
                log.exception("archive-thread: failed to archive '%s'", thread.name)
                await interaction.followup.send("Something went wrong archiving the thread.", ephemeral=True)
