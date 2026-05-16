import json
import logging
from pathlib import Path

import discord
from discord import app_commands

from gtt_bot.config import DISCORD_MSG_LIMIT
from gtt_bot.export.core import download_attachments, extract_urls, fetch_reactions
from gtt_bot.export.formatters import get_forwarded_content, message_to_dict, render_attachments_html, linkify
from gtt_bot.export.state import load_export_state, save_export_state
from gtt_bot.rag.formatters import split_at_sentence

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
        name="export-state",
        description="Incremental export — only new content since last run (GTT Team only)",
    )
    @app_commands.describe(
        format="Output format: text, json, or html",
        reactions="Include reactions (slower, default: no)",
    )
    @app_commands.choices(format=[
        app_commands.Choice(name="all", value="all"),
        app_commands.Choice(name="text", value="text"),
        app_commands.Choice(name="json", value="json"),
        app_commands.Choice(name="html", value="html"),
    ])
    @app_commands.choices(reactions=[
        app_commands.Choice(name="yes", value="yes"),
        app_commands.Choice(name="no", value="no"),
    ])
    async def export_state_cmd(
        interaction: discord.Interaction,
        format: str = "all",
        reactions: str = "no",
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        is_gtt_team = any(r.name in ("GTT Team", "admin") for r in interaction.user.roles)
        if not is_gtt_team:
            await interaction.response.send_message("This command is restricted to GTT Team.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        latest_dir = Path("/exports/latest")
        state, is_bootstrap = load_export_state()

        if is_bootstrap:
            await interaction.followup.send(
                "No state found — running full bootstrap export to `latest/`... this will take a while.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "Running incremental export — fetching only new messages since last run...",
                ephemeral=True,
            )

        latest_dir.mkdir(parents=True, exist_ok=True)
        guild = interaction.guild
        new_state = {}
        exported = []
        skipped = []

        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not perms.read_messages or not perms.read_message_history:
                skipped.append(channel.name)
                continue

            try:
                channel_id = str(channel.id)
                last_message_id = state.get(channel_id)

                messages = []
                if last_message_id and not is_bootstrap:
                    after_obj = discord.Object(id=int(last_message_id))
                    async for msg in channel.history(limit=None, after=after_obj, oldest_first=True):
                        messages.append(msg)
                else:
                    async for msg in channel.history(limit=None, oldest_first=True):
                        messages.append(msg)

                if not messages:
                    if not is_bootstrap:
                        exported.append(f"{channel.name} (0 new messages)")
                    else:
                        skipped.append(channel.name)
                    continue

                new_state[channel_id] = str(messages[-1].id)

                reactions_map = {}
                if reactions == "yes":
                    for msg in messages:
                        if msg.reactions:
                            reactions_map[str(msg.id)] = await fetch_reactions(msg)

                formats_to_write = ["text", "json", "html"] if format == "all" else [format]

                for fmt in formats_to_write:
                    ext = "txt" if fmt == "text" else fmt
                    fpath = latest_dir / f"{channel.name}.{ext}"

                    if fmt == "text":
                        lines_out = []
                        for msg in messages:
                            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                            rxn = reactions_map.get(str(msg.id), {})
                            rxn_str = " " + " ".join(f"{e}({len(u)})" for e, u in rxn.items()) if rxn else ""
                            fwd = get_forwarded_content(msg)
                            fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
                            att_str = " ".join(f"[{a.filename}]" for a in msg.attachments) if msg.attachments else ""
                            text = (msg.content or "") + ((" " + att_str) if att_str else "") + fwd_str
                            lines_out.append(f"[{ts}] {msg.author.display_name}: {text}{rxn_str}")
                        new_content = "\n".join(lines_out)
                        if fpath.exists() and not is_bootstrap:
                            existing = fpath.read_text(encoding="utf-8")
                            fpath.write_text(existing + "\n" + new_content, encoding="utf-8")
                        else:
                            fpath.write_text(new_content, encoding="utf-8")

                    elif fmt == "json":
                        records = [message_to_dict(msg, reactions_map.get(str(msg.id))) for msg in messages]
                        if fpath.exists() and not is_bootstrap:
                            existing = json.loads(fpath.read_text(encoding="utf-8"))
                            existing.extend(records)
                            fpath.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
                        else:
                            fpath.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

                    elif fmt == "html":
                        rows = []
                        for msg in messages:
                            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                            author = discord.utils.escape_markdown(msg.author.display_name)
                            fwd = get_forwarded_content(msg)
                            fwd_html = f'<div class="fwd">↩ {linkify(discord.utils.escape_markdown(fwd))}</div>' if fwd else ""
                            body = (linkify(discord.utils.escape_markdown(msg.content)) if msg.content else "") + fwd_html
                            rxn = reactions_map.get(str(msg.id), {})
                            rxn_str = " ".join(f'<span class="rxn">{e} {len(u)}</span>' for e, u in rxn.items())
                            att_html = render_attachments_html(msg, channel.name)
                            rows.append(
                                f'<tr><td class="ts">{ts}</td><td class="author">{author}</td>'
                                f'<td class="content">{body}{att_html} {rxn_str}</td></tr>'
                            )
                        new_rows = "\n".join(rows)
                        if fpath.exists() and not is_bootstrap:
                            existing = fpath.read_text(encoding="utf-8")
                            fpath.write_text(existing.replace("</table>", new_rows + "\n</table>"), encoding="utf-8")
                        else:
                            html_out = (
                                f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{channel.name}</title>\n'
                                f"<style>{_HTML_STYLE}</style></head><body>\n"
                                f"<h2>#{channel.name}</h2><table>{new_rows}</table></body></html>"
                            )
                            fpath.write_text(html_out, encoding="utf-8")

                att_dir = latest_dir / f"{channel.name}-attachments"
                att_count = await download_attachments(messages, att_dir)
                if att_count == 0 and att_dir.exists() and not any(att_dir.iterdir()):
                    att_dir.rmdir()

                urls_content = extract_urls(messages)
                url_count = 0
                if urls_content:
                    urls_file = latest_dir / f"{channel.name}-urls.txt"
                    if urls_file.exists() and not is_bootstrap:
                        existing_urls = urls_file.read_text(encoding="utf-8")
                        urls_file.write_text(existing_urls + "\n" + urls_content, encoding="utf-8")
                    else:
                        urls_file.write_text(urls_content, encoding="utf-8")
                    url_count = len(urls_content.splitlines())

                exported.append(
                    f"{channel.name} ({len(messages)} new msgs, {att_count} att, {url_count} urls)"
                )
                log.info("export-state %s — %d new messages", channel.name, len(messages))

            except Exception:
                skipped.append(channel.name)
                log.exception("export-state failed for channel %s", channel.name)

        state.update(new_state)
        save_export_state(state)

        mode = "Bootstrap" if is_bootstrap else "Incremental"
        summary = (
            f"**{mode} export complete** — saved to `{latest_dir}`\n\n"
            f"**Updated ({len(exported)}):**\n"
            + "\n".join(f"• {c}" for c in exported[:40])
        )
        if len(exported) > 40:
            summary += f"\n... and {len(exported) - 40} more"
        if skipped:
            summary += f"\n\n**Skipped ({len(skipped)}):** {', '.join(skipped[:20])}"

        try:
            dm = await interaction.user.create_dm()
            for chunk in split_at_sentence(summary):
                await dm.send(chunk)
            try:
                await interaction.followup.send(f"{mode} export complete — summary sent to your DMs.", ephemeral=True)
            except Exception:
                pass
        except discord.Forbidden:
            try:
                await interaction.followup.send(summary[:DISCORD_MSG_LIMIT], ephemeral=True)
            except Exception:
                log.warning("Could not send export-state summary — token expired and DMs disabled")
