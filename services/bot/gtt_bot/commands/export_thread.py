import io
import json
import logging
import zipfile

import discord
from discord import app_commands

from gtt_bot.export.core import fetch_reactions
from gtt_bot.export.formatters import (
    format_thread_bootstrap_html,
    get_forwarded_content,
    linkify,
    message_to_dict,
    render_attachments_html,
)

log = logging.getLogger("bot")

_HTML_STYLE = (
    "body{font-family:sans-serif;background:#1e1e2e;color:#cdd6f4;padding:20px}"
    "table{border-collapse:collapse;width:100%}td{padding:4px 8px;vertical-align:top;border-bottom:1px solid #313244}"
    ".ts{color:#6c7086;white-space:nowrap;width:140px}.author{color:#89b4fa;width:160px;font-weight:bold}"
    ".content{word-break:break-word}.rxn{background:#313244;border-radius:4px;padding:2px 6px;margin:2px;font-size:0.85em}"
    "a{color:#89dceb}img{border:1px solid #313244}.fwd{color:#a6adc8;border-left:3px solid #45475a;padding-left:8px;margin-top:4px;font-size:0.9em}"
)


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="export-thread",
        description="Export this thread to text, JSON, or HTML",
    )
    @app_commands.describe(format="Output format: text, json, html, or bootstrap")
    @app_commands.choices(format=[
        app_commands.Choice(name="text", value="text"),
        app_commands.Choice(name="json", value="json"),
        app_commands.Choice(name="html", value="html"),
        app_commands.Choice(name="bootstrap", value="bootstrap"),
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
        safe_name = "thread-GTT-Bot"

        # Build export content
        if format == "text":
            lines = []
            for msg in messages:
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                rxn = reactions_map.get(str(msg.id), {})
                rxn_str = " " + " ".join(f"{e}({len(u)})" for e, u in rxn.items()) if rxn else ""
                fwd = get_forwarded_content(msg)
                fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
                att_str = " ".join(f"[{a.filename}]" for a in msg.attachments) if msg.attachments else ""
                text = (msg.content or "") + ((" " + att_str) if att_str else "") + fwd_str
                lines.append(f"[{ts}] {msg.author.display_name}: {text}{rxn_str}")
            content = "\n".join(lines).encode("utf-8")
            ext = "txt"

        elif format == "json":
            records = [message_to_dict(msg, reactions_map.get(str(msg.id))) for msg in messages]
            content = json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")
            ext = "json"

        elif format == "html":
            rows = []
            for msg in messages:
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                author = discord.utils.escape_markdown(msg.author.display_name)
                fwd = get_forwarded_content(msg)
                fwd_html = f'<div class="fwd">↩ {linkify(discord.utils.escape_markdown(fwd))}</div>' if fwd else ""
                body = (linkify(discord.utils.escape_markdown(msg.content)) if msg.content else "") + fwd_html
                rxn = reactions_map.get(str(msg.id), {})
                rxn_str = " ".join(f'<span class="rxn">{e} {len(u)}</span>' for e, u in rxn.items())
                att_html = render_attachments_html(msg, safe_name)
                rows.append(
                    f'<tr><td class="ts">{ts}</td><td class="author">{author}</td>'
                    f'<td class="content">{body}{att_html} {rxn_str}</td></tr>'
                )
            html = (
                f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{thread.name}</title>\n'
                f"<style>{_HTML_STYLE}</style></head><body>\n"
                f"<h2>{thread.name} — {len(messages)} messages</h2>\n"
                f'<table>{"".join(rows)}</table></body></html>'
            )
            content = html.encode("utf-8")
            ext = "html"

        elif format == "bootstrap":
            html = format_thread_bootstrap_html(thread.name, messages, reactions_map)
            content = html.encode("utf-8")
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
