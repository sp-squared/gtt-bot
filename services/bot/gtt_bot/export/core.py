import json
import logging
from pathlib import Path

import aiohttp
import discord

from gtt_bot.config import URL_RE
from gtt_bot.export.formatters import (
    get_forwarded_content, render_attachments_html, message_to_dict, linkify,
    build_html_rows, build_html_document, format_thread_bootstrap_html,
    att_and_sticker_str, resolve_mentions,
)

log = logging.getLogger("bot")


async def _download_file(session: aiohttp.ClientSession, url: str, filepath: Path) -> bool:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                filepath.write_bytes(await resp.read())
                return True
    except Exception:
        log.warning("Failed to download %s", url)
    return False


async def download_attachments(messages: list, attachments_dir) -> int:
    """Download all attachments from messages. Returns count downloaded."""
    attachments_dir = Path(attachments_dir)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    async with aiohttp.ClientSession() as session:
        for msg in messages:
            for attachment in msg.attachments:
                filepath = attachments_dir / f"{msg.id}_{attachment.filename}"
                if await _download_file(session, attachment.url, filepath):
                    count += 1
            for sticker in msg.stickers:
                if sticker.format == discord.StickerFormatType.lottie:
                    continue
                ext = "gif" if sticker.format == discord.StickerFormatType.gif else "png"
                filepath = attachments_dir / f"sticker_{sticker.id}_{sticker.name}.{ext}"
                await _download_file(session, str(sticker.url), filepath)
    return count


async def fetch_reactions(message: discord.Message) -> dict:
    """Fetch all reactions and who reacted for a message."""
    result = {}
    for reaction in message.reactions:
        emoji_str = str(reaction.emoji)
        users = []
        try:
            async for user in reaction.users():
                users.append(user.display_name)
        except Exception:
            pass
        result[emoji_str] = users
    return result


async def fetch_thread_messages(thread: discord.Thread, limit) -> list:
    """Fetch all messages from a thread, excluding the zero-content thread_starter_message system record."""
    messages = []
    try:
        async for msg in thread.history(limit=limit, oldest_first=True):
            if msg.type != discord.MessageType.thread_starter_message:
                messages.append(msg)
    except Exception:
        log.warning("Failed to fetch thread %s", thread.name)
    return messages


def extract_urls(messages: list) -> str:
    """Extract all URLs from messages into a deduplicated list."""
    seen = []
    lines = []
    for msg in messages:
        urls = URL_RE.findall(msg.content)
        for url in urls:
            if url not in seen:
                seen.append(url)
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {msg.author.display_name}: {url}")
    return "\n".join(lines)



async def export_channel_data(
    channel: discord.TextChannel,
    export_dir,
    fmt: str,
    fetch_limit,
    fetch_reactions_flag: bool = True,
) -> dict:
    """Export a single channel — messages, threads, pins, attachments, URLs. Returns stats."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    messages = []
    async for msg in channel.history(limit=fetch_limit, oldest_first=True):
        messages.append(msg)

    if not messages:
        return {"messages": 0, "attachments": 0, "urls": 0, "threads": 0, "pinned": 0}

    reactions_map = {}
    if fetch_reactions_flag:
        for msg in messages:
            if msg.reactions:
                reactions_map[str(msg.id)] = await fetch_reactions(msg)

    # Fetch threads (active + archived)
    thread_count = 0
    threads_dir = export_dir / f"{channel.name}-threads"
    all_threads = list(channel.threads)
    try:
        async for thread in channel.archived_threads(limit=None):
            all_threads.append(thread)
    except Exception:
        pass

    for thread in all_threads:
        thread_msgs = await fetch_thread_messages(thread, fetch_limit)
        if not thread_msgs:
            continue
        threads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = thread.name.replace("/", "-").replace("\\", "-")[:80]

        if fmt == "html":
            thread_rxn_map = {}
            if fetch_reactions_flag:
                for tmsg in thread_msgs:
                    if tmsg.reactions:
                        thread_rxn_map[str(tmsg.id)] = await fetch_reactions(tmsg)
            html_content = format_thread_bootstrap_html(thread.name, thread_msgs, thread_rxn_map)
            (threads_dir / f"{safe_name}.html").write_text(html_content, encoding="utf-8")
        elif fmt == "json":
            records_t = [message_to_dict(tmsg) for tmsg in thread_msgs]
            (threads_dir / f"{safe_name}.json").write_text(
                json.dumps(records_t, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            lines = []
            for msg in thread_msgs:
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                att_str = att_and_sticker_str(msg)
                fwd = get_forwarded_content(msg)
                fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
                text = resolve_mentions(msg.system_content or msg.content or "", msg) + ((" " + att_str) if att_str else "") + fwd_str
                lines.append(f"[{ts}] {msg.author.display_name}: {text}")
            (threads_dir / f"{safe_name}.txt").write_text("\n".join(lines), encoding="utf-8")
        thread_count += 1

    # Pinned messages
    pinned_count = 0
    try:
        pinned = await channel.pins()
        if pinned:
            pin_lines = []
            for msg in pinned:
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                pin_lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
            pin_file = export_dir / f"{channel.name}-pinned.txt"
            pin_file.write_text("\n".join(pin_lines), encoding="utf-8")
            pinned_count = len(pinned)
    except Exception:
        pass

    ext = "txt" if fmt == "text" else fmt
    filepath = export_dir / f"{channel.name}.{ext}"

    if fmt == "text":
        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
            rxn = reactions_map.get(str(msg.id), {})
            rxn_str = " " + " ".join(f"{e}({len(u)})" for e, u in rxn.items()) if rxn else ""
            att_str = att_and_sticker_str(msg)
            fwd = get_forwarded_content(msg)
            fwd_str = f" [Forwarded: {fwd}]" if fwd else ""
            text = resolve_mentions(msg.system_content or msg.content or "", msg) + ((" " + att_str) if att_str else "") + fwd_str
            if not text.strip():
                msg_type = getattr(msg.type, "name", str(msg.type)) if msg.type else "unknown"
                text = f"[system: {msg_type}]"
            lines.append(f"[{ts}] {msg.author.display_name}: {text}{rxn_str}")
        filepath.write_text("\n".join(lines), encoding="utf-8")

    elif fmt == "json":
        records = [message_to_dict(msg, reactions_map.get(str(msg.id))) for msg in messages]
        filepath.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    elif fmt == "html":
        msgs_by_id = {str(m.id): m for m in messages}
        rows = build_html_rows(messages, reactions_map, channel.name, msgs_by_id)
        filepath.write_text(build_html_document(channel.name, rows, len(messages)), encoding="utf-8")

    att_dir = export_dir / f"{channel.name}-attachments"
    att_count = await download_attachments(messages, att_dir)
    if att_count == 0 and att_dir.exists():
        try:
            att_dir.rmdir()
        except Exception:
            pass

    urls_content = extract_urls(messages)
    url_count = 0
    if urls_content:
        urls_file = export_dir / f"{channel.name}-urls.txt"
        urls_file.write_text(urls_content, encoding="utf-8")
        url_count = len(urls_content.splitlines())

    return {
        "messages": len(messages),
        "attachments": att_count,
        "urls": url_count,
        "threads": thread_count,
        "pinned": pinned_count,
    }
