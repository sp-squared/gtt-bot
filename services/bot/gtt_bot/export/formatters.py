import logging

import discord

from gtt_bot.config import IMAGE_EXTS, CHANNEL_MENTION_RE, CLEAN_URL_RE, USER_MENTION_RE, ROLE_MENTION_RE

HTML_STYLE = (
    "body{font-family:sans-serif;background:#1e1e2e;color:#cdd6f4;padding:20px}"
    "table{border-collapse:collapse;width:100%}td{padding:4px 8px;vertical-align:top;border-bottom:1px solid #313244}"
    ".ts{color:#6c7086;white-space:nowrap;width:140px}.author{color:#89b4fa;width:160px;font-weight:bold}"
    ".content{word-break:break-word}.rxn{background:#313244;border-radius:4px;padding:2px 6px;margin:2px;font-size:0.85em}"
    "a{color:#89dceb}img{border:1px solid #313244}"
    ".fwd{color:#a6adc8;border-left:3px solid #45475a;padding-left:8px;margin-top:4px;font-size:0.9em}"
    ".reply-ref{color:#89b4fa;font-size:0.82em;border-left:3px solid #89b4fa;padding-left:6px;margin-bottom:3px}"
)

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


def resolve_mentions(content: str, msg) -> str:
    """Replace <@USER_ID> and <@&ROLE_ID> with @DisplayName / @RoleName."""
    if not content:
        return content
    user_map = {str(m.id): m.display_name for m in msg.mentions}
    role_map = {str(r.id): r.name for r in getattr(msg, "role_mentions", [])}
    content = USER_MENTION_RE.sub(
        lambda m: f"@{user_map.get(m.group(1), m.group(1))}", content
    )
    content = ROLE_MENTION_RE.sub(
        lambda m: f"@{role_map.get(m.group(1), m.group(1))}", content
    )
    return content


def att_and_sticker_str(msg) -> str:
    """Text notation for attachments and stickers (for plain-text export lines)."""
    parts = [f"[{a.filename}]" for a in msg.attachments]
    parts += [f"[Sticker: {s.name}]" for s in msg.stickers]
    return " ".join(parts) if parts else ""


def render_attachments_html(msg, channel_name: str) -> str:
    """Render attachments and stickers as inline images or clickable links with relative paths."""
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
    for sticker in msg.stickers:
        if sticker.format == discord.StickerFormatType.lottie:
            parts.append(f'<span title="{sticker.name}">🎭 {sticker.name}</span>')
        else:
            ext = "gif" if sticker.format == discord.StickerFormatType.gif else "png"
            rel_path = f"{channel_name}-attachments/sticker_{sticker.id}_{sticker.name}.{ext}"
            parts.append(
                f"<a href=\"{rel_path}\" target=\"_blank\">"
                f"<img src=\"{rel_path}\" alt=\"Sticker: {sticker.name}\" "
                f"style=\"max-width:160px;max-height:160px;display:block;margin:4px 0;border-radius:4px;\" "
                f"onerror=\"this.style.display=&quot;none&quot;\"></a>"
            )
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


def format_thread_bootstrap_html(
    thread_name: str,
    messages: list,
    reactions_map: dict,
    tags: list = None,
) -> str:
    """Render an exported thread/forum post as a self-contained Bootstrap 5 HTML file."""
    import html as _html

    max_len = max((len(m.content or "") for m in messages), default=1)
    max_rxn = max(
        (sum(len(u) for u in reactions_map.get(str(m.id), {}).values()) for m in messages),
        default=1,
    )

    def _bar(pct: int, color: str, label: str, value_str: str) -> str:
        return f"""
            <div class="score-row">
              <span class="score-label">{label}</span>
              <div class="score-track">
                <div class="score-fill" style="width:{pct}%;background:{color}"></div>
              </div>
              <span class="score-val">{value_str}</span>
            </div>"""

    def _card(index: int, msg) -> str:
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
        author = _html.escape(msg.author.display_name)
        content = _html.escape(resolve_mentions(msg.system_content or msg.content or "", msg)).replace("\n", "<br>")
        rxn = reactions_map.get(str(msg.id), {})
        rxn_total = sum(len(u) for u in rxn.values())
        msg_len = len(msg.content or "")

        len_pct = min(int(msg_len / max_len * 100), 100)
        rxn_pct = min(int(rxn_total / max_rxn * 100), 100) if max_rxn else 0

        bars = _bar(len_pct, "#1f6feb", "length", str(msg_len))
        if reactions_map:
            bars += _bar(rxn_pct, "#3fb950", "reactions", str(rxn_total))

        rxn_badges = " ".join(
            f'<span class="badge" style="background:#313244;font-size:0.8em">'
            f'{_html.escape(e)} {len(u)}</span>'
            for e, u in rxn.items()
        )

        reply_badge = ""
        if msg.reference:
            reply_badge = f'<span class="badge bg-secondary ms-2">↩ reply</span>'

        pinned_badge = '<span class="badge bg-warning text-dark ms-2">📌 pinned</span>' if msg.pinned else ""

        att_links = " ".join(
            f'<a href="{_html.escape(a.url)}" target="_blank" class="badge bg-secondary text-decoration-none">'
            f'📎 {_html.escape(a.filename)}</a>'
            for a in msg.attachments
        )

        sticker_imgs = ""
        for sticker in msg.stickers:
            if sticker.format == discord.StickerFormatType.lottie:
                sticker_imgs += f'<span class="badge bg-secondary ms-1">🎭 {_html.escape(sticker.name)}</span>'
            else:
                sticker_imgs += (
                    f'<img src="{_html.escape(str(sticker.url))}" '
                    f'alt="Sticker: {_html.escape(sticker.name)}" '
                    f'style="max-width:160px;max-height:160px;display:block;margin:4px 0;border-radius:4px;">'
                )

        return f"""
        <div class="card mb-4 border-0 shadow-sm chunk-card">
          <div class="card-header py-2">
            <div class="d-flex justify-content-between align-items-start gap-3">
              <div>
                <span class="badge bg-primary font-monospace fs-6">[{index}] {author}</span>
                {reply_badge}{pinned_badge}
                <span class="text-muted ms-2" style="font-size:0.8em">{ts}</span>
              </div>
              <div class="score-block">{bars}</div>
            </div>
          </div>
          <div class="card-body">
            <pre class="chunk-pre mb-0"><code>{content}</code></pre>
            {(f'<div class="mt-2">{sticker_imgs}</div>') if sticker_imgs else ""}
            {(f'<div class="mt-2">{rxn_badges}</div>') if rxn_badges else ""}
            {(f'<div class="mt-2">{att_links}</div>') if att_links else ""}
          </div>
        </div>"""

    cards = "".join(_card(i, m) for i, m in enumerate(messages, 1))
    msg_count = len(messages)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html.escape(thread_name)}</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        crossorigin="anonymous">
  <style>
    body {{ background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',system-ui,sans-serif }}
    .card {{ background:#161b22; border:1px solid #30363d !important }}
    .card-header {{ background:#1c2128; border-bottom:1px solid #30363d }}
    pre.chunk-pre {{ background:#0d1117; border-radius:6px; padding:12px;
                     color:#c9d1d9; white-space:pre-wrap; word-break:break-word;
                     font-size:0.88rem; max-height:400px; overflow-y:auto }}
    .score-block {{ min-width:200px }}
    .score-row {{ display:flex; align-items:center; gap:6px; margin-bottom:3px }}
    .score-label {{ width:60px; font-size:0.72rem; color:#8b949e; text-align:right }}
    .score-track {{ flex:1; height:6px; background:#21262d; border-radius:3px; overflow:hidden }}
    .score-fill {{ height:100%; border-radius:3px }}
    .score-val {{ width:36px; font-size:0.72rem; color:#8b949e; font-family:monospace }}
    .query-box {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px 24px }}
    .query-box .query-text {{ font-size:1.4rem; font-weight:600; color:#e6edf3 }}
    .query-box .query-sub {{ font-family:monospace; font-size:0.85rem; color:#8b949e; margin-top:4px }}
    a {{ color:#58a6ff }}
  </style>
</head>
<body class="p-4">
  <div class="container-xl">

    <div class="query-box mb-4">
      <div class="query-label text-uppercase fw-bold mb-2"
           style="font-size:0.7rem;letter-spacing:.1em;color:#8b949e">THREAD</div>
      <div class="query-text">{_html.escape(thread_name)}</div>
      {"".join(f'<span class="badge me-1 mt-2" style="background:#388bfd;font-size:0.75em">{_html.escape(t)}</span>' for t in (tags or []))}
      <div class="query-sub">{msg_count} messages</div>
    </div>

    <h6 class="text-uppercase fw-bold mb-3"
        style="font-size:0.7rem;letter-spacing:.1em;color:#8b949e">MESSAGES</h6>
    {cards}

  </div>
</body>
</html>"""


def format_forum_index_html(channel_name: str, posts: list, post_ext: str) -> str:
    """Render a Bootstrap index page for a forum channel listing all posts with links."""
    import html as _html

    def _card(post: dict) -> str:
        title = _html.escape(post["title"])
        author = _html.escape(post["author"])
        ts = post["created_at"]
        msg_count = post["message_count"]
        tags_html = " ".join(
            f'<span class="badge me-1" style="background:#388bfd;font-size:0.72em">{_html.escape(t)}</span>'
            for t in post["tags"]
        )
        archived_badge = '<span class="badge bg-secondary ms-1" style="font-size:0.72em">archived</span>' if post["archived"] else ""
        link = f"{channel_name}-posts/{post['safe_name']}.{post_ext}"
        return f"""
        <div class="card mb-3 border-0 shadow-sm">
          <div class="card-body py-3">
            <div class="d-flex justify-content-between align-items-start gap-3">
              <div>
                <a href="{link}" class="fw-semibold text-decoration-none" style="color:#58a6ff;font-size:1rem">{title}</a>
                {archived_badge}
                <div class="mt-1">{tags_html}</div>
                <div class="mt-1" style="font-size:0.82rem;color:#8b949e">{author}</div>
              </div>
              <div class="text-end flex-shrink-0">
                <div style="font-size:0.8rem;color:#8b949e">{ts}</div>
                <div style="font-size:0.8rem;color:#8b949e">{msg_count} messages</div>
              </div>
            </div>
          </div>
        </div>"""

    cards = "".join(_card(p) for p in posts)
    post_count = len(posts)
    escaped_name = _html.escape(channel_name)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>#{escaped_name} (Forum)</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        crossorigin="anonymous">
  <style>
    body {{ background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',system-ui,sans-serif }}
    .card {{ background:#161b22; border:1px solid #30363d !important }}
    a {{ color:#58a6ff }}
  </style>
</head>
<body class="p-4">
  <div class="container-xl">
    <div class="mb-4" style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px 24px">
      <div style="font-size:0.7rem;letter-spacing:.1em;color:#8b949e;text-transform:uppercase;font-weight:bold;margin-bottom:8px">FORUM</div>
      <div style="font-size:1.4rem;font-weight:600;color:#e6edf3">#{escaped_name}</div>
      <div style="font-family:monospace;font-size:0.85rem;color:#8b949e;margin-top:4px">{post_count} posts</div>
    </div>
    <h6 class="text-uppercase fw-bold mb-3" style="font-size:0.7rem;letter-spacing:.1em;color:#8b949e">POSTS</h6>
    {cards}
  </div>
</body>
</html>"""


def build_html_rows(
    messages: list,
    reactions_map: dict,
    channel_name: str,
    messages_by_id: dict = None,
) -> list[str]:
    """Build HTML <tr> rows for a channel export table, including reply context."""
    rows = []
    for msg in messages:
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
        author = discord.utils.escape_markdown(msg.author.display_name)

        reply_html = ""
        if msg.reference and msg.reference.message_id:
            ref = (messages_by_id or {}).get(str(msg.reference.message_id))
            if ref:
                preview = discord.utils.escape_markdown(resolve_mentions((ref.content or "")[:80], ref))
                reply_html = (
                    f'<div class="reply-ref">↩ <b>{discord.utils.escape_markdown(ref.author.display_name)}</b>'
                    f": {linkify(preview)}</div>"
                )
            else:
                reply_html = '<div class="reply-ref">↩ reply</div>'

        fwd = get_forwarded_content(msg)
        fwd_html = f'<div class="fwd">↩ {linkify(discord.utils.escape_markdown(fwd))}</div>' if fwd else ""
        display_text = resolve_mentions(msg.system_content or msg.content or "", msg)
        body = reply_html + (linkify(discord.utils.escape_markdown(display_text)) if display_text else "") + fwd_html
        rxn = reactions_map.get(str(msg.id), {})
        rxn_str = " ".join(f'<span class="rxn">{e} {len(u)}</span>' for e, u in rxn.items())
        att_html = render_attachments_html(msg, channel_name)
        rows.append(
            f'<tr><td class="ts">{ts}</td><td class="author">{author}</td>'
            f'<td class="content">{body}{att_html} {rxn_str}</td></tr>'
        )
    return rows


def build_html_document(title: str, rows: list[str], messages_count: int = None) -> str:
    """Wrap HTML rows in a complete standalone HTML document."""
    h2_text = f"#{title}" + (f" — {messages_count} messages" if messages_count is not None else "")
    return (
        f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{title}</title>\n'
        f"<style>{HTML_STYLE}</style></head><body>\n"
        f"<h2>{h2_text}</h2>\n"
        f'<table>{"".join(rows)}</table></body></html>'
    )


def message_to_dict(msg: discord.Message, reactions: dict = None) -> dict:
    """Convert a discord.Message to a serializable dict with full metadata."""
    sc = msg.system_content
    record = {
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
    if sc and sc != msg.content:
        record["system_content"] = sc
    return record
