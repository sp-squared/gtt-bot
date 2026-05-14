import json
import logging
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

from gtt_bot.export.core import download_attachments, export_channel_data
from gtt_bot.rag.formatters import split_at_sentence

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="export-all", description="Export all server channels to local disk (GTT Team only)")
    @app_commands.describe(
        format="Output format: text, json, or html",
        limit="Messages per channel (default 500, 0 = unlimited)",
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
    async def export_all(
        interaction: discord.Interaction,
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

        timestamp = discord.utils.utcnow().strftime("%Y-%m-%d-%H-%M")
        export_root = Path("/exports") / timestamp
        export_root.mkdir(parents=True, exist_ok=True)

        guild = interaction.guild
        exported = []
        skipped = []

        # Export server assets — emoji and member snapshot
        assets_dir = export_root / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        emoji_dir = assets_dir / "emoji"
        emoji_dir.mkdir(parents=True, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            for emoji in guild.emojis:
                url = str(emoji.url)
                ext = "gif" if emoji.animated else "png"
                filepath = emoji_dir / f"{emoji.name}.{ext}"
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            filepath.write_bytes(await resp.read())
                except Exception:
                    pass

        members_data = []
        for member in guild.members:
            members_data.append({
                "id": str(member.id),
                "username": str(member),
                "display_name": member.display_name,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "roles": [r.name for r in member.roles if r.name != "@everyone"],
            })
        (assets_dir / "members.json").write_text(
            json.dumps(members_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        await interaction.followup.send(
            f"Starting export of all channels to `{export_root}`...", ephemeral=True
        )

        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not perms.read_messages or not perms.read_message_history:
                skipped.append(channel.name)
                continue

            try:
                stats = await export_channel_data(
                    channel, export_root, format, fetch_limit,
                    fetch_reactions_flag=(reactions == "yes"),
                )
                if stats["messages"] == 0:
                    skipped.append(channel.name)
                    continue
                exported.append(
                    f"{channel.name} ({stats['messages']} msgs, "
                    f"{stats['attachments']} att, {stats['urls']} urls, "
                    f"{stats['threads']} threads, {stats['pinned']} pinned)"
                )
                log.info("Exported %s — %s", channel.name, stats)
            except Exception:
                skipped.append(channel.name)
                log.exception("Failed to export channel %s", channel.name)

        summary = (
            f"**Export complete** — saved to `{export_root}`\n\n"
            f"**Exported ({len(exported)}):**\n"
            + "\n".join(f"• {c}" for c in exported[:40])
        )
        if len(exported) > 40:
            summary += f"\n... and {len(exported) - 40} more"
        if skipped:
            summary += f"\n\n**Skipped ({len(skipped)}):** {', '.join(skipped)}"

        try:
            dm = await interaction.user.create_dm()
            for chunk in split_at_sentence(summary):
                await dm.send(chunk)
            try:
                await interaction.followup.send("Export complete — summary sent to your DMs.", ephemeral=True)
            except Exception:
                pass  # Token may have expired — DM was already sent
        except discord.Forbidden:
            try:
                await interaction.followup.send(summary[:2000], ephemeral=True)
            except Exception:
                log.warning("Could not send export-all summary — token expired and DMs disabled")
