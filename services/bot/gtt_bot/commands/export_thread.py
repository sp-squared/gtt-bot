import io
import json
import logging
import zipfile

import discord
from discord import app_commands

from gtt_bot.export.core import fetch_reactions
from gtt_bot.export.formatters import get_forwarded_content, message_to_dict, format_thread_bootstrap_html, att_and_sticker_str

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="export-thread",
        description="Export this thread to text, JSON, or HTML",
    )
    @app_commands.describe(format="Output format: text, json, or html")
    @app_commands.choices(format=[
        app_commands.Choice(name="text", value="text"),
        app_commands.Choice(name="json", value="json"),
        app_commands.Choice(name="html", value="html"),
    ])
    @app_commands.choices(reactions=[
        app_commands.Choice(name="yes", value="yes"),
        app_commands.Choice(name="no", value="no"),
    ])
    @app_commands.describe(reactions="Include reactions (default: no)")
    async def export_thread(
        interaction: discord.Interaction,
        format: str,
        reactions: str = "no",
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Run this command inside the thread you want to export.", ephemeral=True
            )
            return

        thread = interaction.channel
        await interaction.response.defer(ephemeral=True)

        # Fetch starter message (the question that created the thread) from parent channel
        messages = []
        if thread.parent:
            try:
                starter = await thread.parent.fetch_message(thread.id)
                messages.append(starter)
            except (discord.NotFound, discord.Forbidden):
                pass

        async for msg in thread.history(limit=None, oldest_first=True):
            if msg.type != discord.MessageType.thread_starter_message:
                messages.append(msg)

        if not messages:
            await interaction.followup.send("This thread has no messages.", ephemeral=True)
            return

        # Fetch reactions if requested
        reactions_map = {}
        if reactions == "yes":
            for msg in messages:
                if msg.reactions:
                    reactions_map[str(msg.id)] = await fetch_reactions(msg)

        filename_base = "thread-GTT-Bot"

        # Build export content
        if format == "text":
            lines = []
            for msg in messages:
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                rxn = reactions_map.get(str(msg.id), {})
                rxn_str = " " + " ".join(f"{e}({len(u)})" for e, u in rxn.items()) if rxn else ""
                fwd = get_forwarded_content(msg)
                fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
                att_str = att_and_sticker_str(msg)
                text = (msg.system_content or msg.content or "") + ((" " + att_str) if att_str else "") + fwd_str
                if not text.strip():
                    msg_type = getattr(msg.type, "name", str(msg.type)) if msg.type else "unknown"
                    text = f"[system: {msg_type}]"
                lines.append(f"[{ts}] {msg.author.display_name}: {text}{rxn_str}")
            content = "\n".join(lines).encode("utf-8")
            ext = "txt"

        elif format == "json":
            records = [message_to_dict(msg, reactions_map.get(str(msg.id))) for msg in messages]
            content = json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")
            ext = "json"

        elif format == "html":
            content = format_thread_bootstrap_html(thread.name, messages, reactions_map).encode("utf-8")
            ext = "html"

        # Zip and send via DM
        _buf = io.BytesIO()
        with zipfile.ZipFile(_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{filename_base}.{ext}", content)
        zip_bytes = _buf.getvalue()  # read all bytes regardless of buffer position

        timestamp = discord.utils.utcnow().strftime("%Y%m%d-%H%M%S")
        zip_filename = f"{filename_base}-{timestamp}.zip"

        if len(zip_bytes) > 25 * 1024 * 1024:
            await interaction.followup.send(
                "Export too large for Discord (25MB limit).", ephemeral=True
            )
            return

        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                f"Thread export: **{thread.name}** — {len(messages)} messages ({format})",
                file=discord.File(io.BytesIO(zip_bytes), filename=zip_filename),
            )
            await interaction.followup.send("Export sent to your DMs.", ephemeral=True)
            log.info("export-thread: %s (%d msgs, %s) for %s", thread.name, len(messages), format, interaction.user)
        except discord.Forbidden:
            await interaction.followup.send(
                "Could not DM you the export — enable DMs from server members.", ephemeral=True
            )
        except Exception:
            log.exception("export-thread failed")
            await interaction.followup.send("Something went wrong during export.", ephemeral=True)
