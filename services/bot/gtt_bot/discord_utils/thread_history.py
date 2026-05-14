import logging

import discord

log = logging.getLogger("bot")


async def get_thread_history(channel, client: discord.Client, limit: int = 30) -> list:
    """Fetch last N bot-related messages from a thread and build conversation history.
    Only counts @GTT Bot mentions and bot responses — ignores regular conversation."""
    if not isinstance(channel, discord.Thread):
        return []

    history = []
    try:
        messages = [msg async for msg in channel.history(limit=200)]
        messages.reverse()  # oldest first

        bot_related = []
        for msg in messages:
            if msg.author == client.user:
                # Bot response — strip sources line before adding to history
                msg_content = msg.content
                if "*Sources —" in msg_content:
                    msg_content = msg_content[:msg_content.index("*Sources —")].strip()
                if msg_content:
                    bot_related.append({"role": "assistant", "content": msg_content})
            elif not msg.author.bot and client.user in msg.mentions:
                text = msg.clean_content
                if client.user:
                    text = text.replace(f"@{client.user.name}", "").strip()
                if text:
                    bot_related.append({"role": "user", "content": text})

        history = bot_related[-limit:]

    except Exception:
        log.exception("Failed to fetch thread history")

    return history
