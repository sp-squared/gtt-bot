import logging

import discord

from gtt_bot.config import IMAGE_EXTS, CHANNEL_MENTION_RE, CLEAN_URL_RE

log = logging.getLogger("bot")


def get_forwarded_content(msg) -> str:
    """Extract content from forwarded messages using discord.py v2.5+ MessageSnapshot."""
    try:
        snapshots = getattr(msg, "message_snapshots", None)
        if snapshots:
            parts = []
            for snap in snapshots:
                text = getattr(snap, "content", "") or ""
                if text:
                    parts.append(text)
            if parts:
                return " | ".join(parts)

        # Fallback: try accessing raw Discord payload data directly
        for attr in ("_raw_data", "__dict__"):
            raw = getattr(msg, attr, None)
            if isinstance(raw, dict):
                snaps = raw.get("message_snapshots", [])
                for snap in snaps:
                    inner = snap.get("message", {})
                    text = inner.get("content", "")
                    if text:
                        return f"[Forwarded]: {text}"

        return ""
    except Exception as e:
        log.debug("get_forwarded_content failed: %s", e)
        return ""


def render_attachments_html(msg, channel_name: str) -> str:
    """Render attachments as inline images or clickable links with relative paths."""
    parts = []
    for att in msg.attachments:
        safe_name = f"{msg.id}_{att.filename}"
        rel_path = f"{channel_name}-attachments/{safe_name}"
        ext = ("." + att.filename.rsplit(".", 1)[-1].lower()) if "." in att.filename else ""
        if ext in IMAGE_EXTS:
            parts.append(
                f"<a href=\"{rel_path}\" target=\"_blank\">"
                f"<img src=\"{rel_path}\" alt=\"{att.filename}\" "
                f"style=\"max-width:400px;max-height:300px;display:block;margin:4px 0;border-radius:4px;\" "
                f"onerror=\"this.style.display=&quot;none&quot;\"></a>"
            )
        else:
            parts.append(f"<a href=\"{rel_path}\" target=\"_blank\">&#128206; {att.filename}</a>")
    return " ".join(parts)


def linkify(text: str) -> str:
    """Convert plain URLs to clickable links, handle line breaks and channel mentions cleanly."""
    if not text:
        return text
    text = CHANNEL_MENTION_RE.sub("", text)
    lines = text.split("\n")
    result = []
    for line in lines:
        line = CLEAN_URL_RE.sub(
            lambda m: f'<a href="{m.group()}" target="_blank">{m.group()}</a>',
            line,
        )
        result.append(line)
    return "<br>".join(result)


def message_to_dict(msg: discord.Message, reactions: dict = None) -> dict:
    """Convert a discord.Message to a serializable dict with full metadata."""
    return {
        "id": str(msg.id),
        "timestamp": msg.created_at.isoformat(),
        "author": msg.author.display_name,
        "author_id": str(msg.author.id),
        "author_roles": [r.name for r in msg.author.roles] if isinstance(msg.author, discord.Member) else [],
        "content": msg.content,
        "reply_to_id": str(msg.reference.message_id) if msg.reference else None,
        "attachments": [{"filename": a.filename, "url": a.url} for a in msg.attachments],
        "stickers": [{"id": str(s.id), "name": s.name} for s in msg.stickers],
        "reactions": reactions or {},
        "pinned": msg.pinned,
    }
