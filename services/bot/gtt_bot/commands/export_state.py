import json
import logging
from pathlib import Path

import discord
from discord import app_commands

from gtt_bot.config import DISCORD_MSG_LIMIT
from gtt_bot.export.core import download_attachments, extract_urls, fetch_reactions
from gtt_bot.export.formatters import (
    get_forwarded_content, message_to_dict, linkify,
    build_html_rows, build_html_document, format_thread_bootstrap_html,
    att_and_sticker_str, resolve_mentions,
)
from gtt_bot.export.state import load_export_state, save_export_state
from gtt_bot.rag.formatters import split_at_sentence

log = logging.getLogger("bot")


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
                            att_str = att_and_sticker_str(msg)
                            text = resolve_mentions(msg.system_content or msg.content or "", msg) + ((" " + att_str) if att_str else "") + fwd_str
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
                        msgs_by_id = {str(m.id): m for m in messages}
                        rows = build_html_rows(messages, reactions_map, channel.name, msgs_by_id)
                        if fpath.exists() and not is_bootstrap:
                            existing = fpath.read_text(encoding="utf-8")
                            fpath.write_text(
                                existing.replace("</table>", "\n".join(rows) + "\n</table>"),
                                encoding="utf-8",
                            )
                        else:
                            fpath.write_text(build_html_document(channel.name, rows, len(messages)), encoding="utf-8")

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

                # Threads (always full re-export — no incremental state per thread)
                all_threads = list(channel.threads)
                try:
                    async for t in channel.archived_threads(limit=None):
                        all_threads.append(t)
                except Exception:
                    pass

                thread_count = 0
                for thread in all_threads:
                    thread_msgs = []
                    try:
                        async for tmsg in thread.history(limit=None, oldest_first=True):
                            thread_msgs.append(tmsg)
                    except Exception:
                        log.warning("export-state: failed to fetch thread %s", thread.name)
                        continue
                    if not thread_msgs:
                        continue

                    threads_dir = latest_dir / f"{channel.name}-threads"
                    threads_dir.mkdir(parents=True, exist_ok=True)
                    safe_name = thread.name.replace("/", "-").replace("\\", "-")[:80]

                    thread_rxn_map = {}
                    if reactions == "yes":
                        for tmsg in thread_msgs:
                            if tmsg.reactions:
                                thread_rxn_map[str(tmsg.id)] = await fetch_reactions(tmsg)

                    for tfmt in formats_to_write:
                        if tfmt == "text":
                            lines_t = []
                            for tmsg in thread_msgs:
                                ts = tmsg.created_at.strftime("%Y-%m-%d %H:%M")
                                rxn = thread_rxn_map.get(str(tmsg.id), {})
                                rxn_str = " " + " ".join(f"{e}({len(u)})" for e, u in rxn.items()) if rxn else ""
                                fwd = get_forwarded_content(tmsg)
                                fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
                                att_str = att_and_sticker_str(tmsg)
                                text = resolve_mentions(tmsg.system_content or tmsg.content or "", tmsg) + ((" " + att_str) if att_str else "") + fwd_str
                                lines_t.append(f"[{ts}] {tmsg.author.display_name}: {text}{rxn_str}")
                            (threads_dir / f"{safe_name}.txt").write_text("\n".join(lines_t), encoding="utf-8")
                        elif tfmt == "json":
                            records_t = [message_to_dict(tmsg, thread_rxn_map.get(str(tmsg.id))) for tmsg in thread_msgs]
                            (threads_dir / f"{safe_name}.json").write_text(
                                json.dumps(records_t, indent=2, ensure_ascii=False), encoding="utf-8"
                            )
                        elif tfmt == "html":
                            html_content = format_thread_bootstrap_html(thread.name, thread_msgs, thread_rxn_map)
                            (threads_dir / f"{safe_name}.html").write_text(html_content, encoding="utf-8")

                    thread_count += 1

                exported.append(
                    f"{channel.name} ({len(messages)} new msgs, {att_count} att, {url_count} urls, {thread_count} threads)"
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
