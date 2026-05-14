import io
import logging
import tempfile
import zipfile
from pathlib import Path

import discord
from discord import app_commands

from gtt_bot.export.core import export_channel_data

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="export", description="Export channel history to a file (GTT Team only)")
    @app_commands.describe(
        channel="Channel to export",
        format="Output format: text, json, or html",
        limit="Number of messages to export (default 500, 0 = unlimited)",
        reactions="Include reactions (slower, default: yes)",
    )
    @app_commands.choices(format=[
        app_commands.Choice(name="text", value="text"),
        app_commands.Choice(name="json", value="json"),
        app_commands.Choice(name="html", value="html"),
    ])
    @app_commands.choices(reactions=[
        app_commands.Choice(name="yes", value="yes"),
        app_commands.Choice(name="no", value="no"),
    ])
    async def export(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        format: str,
        limit: int = 500,
        reactions: str = "yes",
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        is_gtt_team = any(r.name in ("GTT Team", "admin") for r in interaction.user.roles)
        if not is_gtt_team:
            await interaction.response.send_message("This command is restricted to GTT Team.", ephemeral=True)
            return

        fetch_limit = None if limit == 0 else max(1, limit)

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            f"Exporting up to {limit} messages from {channel.mention} as `{format}`... this may take a moment.",
            ephemeral=True,
        )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                channel_dir = tmpdir / channel.name
                stats = await export_channel_data(
                    channel, channel_dir, format, fetch_limit,
                    fetch_reactions_flag=(reactions == "yes"),
                )

                if stats["messages"] == 0:
                    await interaction.followup.send("No messages found in that channel.", ephemeral=True)
                    return

                timestamp = discord.utils.utcnow().strftime("%Y%m%d-%H%M%S")
                zip_path = tmpdir / f"{channel.name}-{timestamp}.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in channel_dir.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(tmpdir))

                zip_bytes = zip_path.read_bytes()

            if len(zip_bytes) > 25 * 1024 * 1024:
                await interaction.followup.send(
                    "Export too large for Discord (25MB limit). Try a smaller limit or use /export-all to save to disk.",
                    ephemeral=True,
                )
            else:
                zip_file = discord.File(io.BytesIO(zip_bytes), filename=zip_path.name)
                try:
                    dm = await interaction.user.create_dm()
                    await dm.send(
                        f"Export of #{channel.name} — {stats['messages']} messages, "
                        f"{stats['attachments']} attachments, {stats['urls']} urls, "
                        f"{stats['threads']} threads, {stats['pinned']} pinned ({format})",
                        file=zip_file,
                    )
                    await interaction.followup.send("Export sent to your DMs.", ephemeral=True)
                    log.info("Exported %s stats=%s for %s", channel.name, stats, interaction.user)
                except discord.Forbidden:
                    await interaction.followup.send(
                        "Could not DM you the export — enable DMs from server members.", ephemeral=True
                    )

        except Exception:
            log.exception("Export command failed")
            await interaction.followup.send("Something went wrong during export.", ephemeral=True)
