import asyncio
import logging
import time

import anthropic
import discord
from discord import app_commands

import gtt_bot.globals as G
from gtt_bot.config import (
    COOLDOWN_ANTHROPIC,
    DISCORD_MSG_LIMIT,
    DISCORD_TOKEN,
    MAX_QUESTION_LENGTH,
    REQUIRED_ROLE,
    THREAD_HISTORY_LIMIT,
    TIMEOUT_LEAVE_WINDOW,
)
from gtt_bot.automod.rules import check_automod
from gtt_bot.automod.alerts import send_timeout_leave_alert
from gtt_bot.discord_utils.cooldown import check_cooldown
from gtt_bot.discord_utils.permissions import (
    has_required_role,
    is_allowed_channel,
    is_allowed_guild,
    is_cooldown_exempt,
)
from gtt_bot.discord_utils.thread_history import get_thread_history
from gtt_bot.discord_utils.thread_mode import get_thread_mode
from gtt_bot.rag.anthropic import query_anthropic
from gtt_bot.rag.formatters import format_sources, split_at_sentence
from gtt_bot.rag.retriever import build_retriever, retrieve_context

# Command modules — each exposes setup(tree)
from gtt_bot.commands import archive_thread
from gtt_bot.commands import export_all
from gtt_bot.commands import export_single
from gtt_bot.commands import export_state
from gtt_bot.commands import export_thread
from gtt_bot.commands import glossary
from gtt_bot.commands import knowledge
from gtt_bot.commands import status
from gtt_bot.commands import thread_mode_cmd

log = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# Discord client
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.guild_messages = True
intents.members = True  # required for automod role checks and has_required_role

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def send_answer(message: discord.Message, answer: str, sources: str) -> None:
    """Send answer in a thread or inline depending on per-guild thread mode.

    If the message is already inside a thread we reply inline — Discord does
    not allow threads-within-threads and attempting it raises an error.
    """
    full = f"{answer}\n\n{sources}" if sources else answer

    # Already in a thread — reply inline
    if isinstance(message.channel, discord.Thread):
        for chunk in split_at_sentence(full):
            await message.reply(chunk)
        return

    use_threads = get_thread_mode(message.guild.id) if message.guild else False

    if use_threads and isinstance(message.channel, discord.TextChannel):
        thread_name = (message.clean_content[:80] or "GTT Bot").strip()
        thread = await message.create_thread(name=thread_name)
        for chunk in split_at_sentence(full):
            await thread.send(chunk)
    else:
        for chunk in split_at_sentence(full):
            await message.reply(chunk)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@client.event
async def on_ready() -> None:
    await tree.sync()
    log.info("Slash commands synced")
    log.info("Logged in as %s", client.user)


@client.event
async def on_member_remove(member: discord.Member) -> None:
    entry = G.recent_timeouts.pop(member.id, None)
    if entry is None:
        return
    timeout_ts, rule = entry
    elapsed = time.time() - timeout_ts
    if elapsed <= TIMEOUT_LEAVE_WINDOW:
        await send_timeout_leave_alert(member.guild, member, elapsed, rule)


@client.event
async def on_message(message: discord.Message) -> None:
    # Ignore all bot messages (including self)
    if message.author.bot:
        return

    # Automod runs on every message regardless of whether the bot was mentioned
    await check_automod(message)

    # Only continue processing for direct @mentions of this bot
    if not client.user or client.user not in message.mentions:
        return

    # Guild / channel access control
    if message.guild and not is_allowed_guild(message.guild.id):
        return
    if not is_allowed_channel(message.channel):
        return

    # Role gate — only enforce if REQUIRED_ROLE is configured
    if REQUIRED_ROLE and isinstance(message.author, discord.Member):
        if not has_required_role(message.author):
            await message.reply(
                f"You need the `{REQUIRED_ROLE}` role to use this bot.",
                delete_after=10,
            )
            return

    # Strip the @mention from the question text
    question = message.clean_content.replace(f"@{client.user.name}", "").strip()
    if not question:
        return

    if len(question) > MAX_QUESTION_LENGTH:
        await message.reply(f"Keep it under {MAX_QUESTION_LENGTH} characters.")
        return

    # Cooldown — exempt users and exempt-role members bypass entirely
    if not is_cooldown_exempt(message.author):
        remaining = check_cooldown(
            message.author.id, G.anthropic_cooldowns, COOLDOWN_ANTHROPIC
        )
        if remaining > 0:
            await message.reply(
                f"Slow down — you can ask again in {int(remaining) + 1}s.",
                delete_after=5,
            )
            return
        G.anthropic_cooldowns[message.author.id] = time.time()

    try:
        async with message.channel.typing():
            try:
                nodes = await asyncio.to_thread(retrieve_context, question)
                context = (
                    "\n\n".join(n.get_content() for n in nodes) if nodes else ""
                )

                # For threads, include prior conversation history so Anthropic
                # can give coherent multi-turn replies
                history: list = []
                if isinstance(message.channel, discord.Thread):
                    history = await get_thread_history(
                        message.channel, client, THREAD_HISTORY_LIMIT
                    )

                answer = await asyncio.to_thread(
                    query_anthropic, question, context, history
                )
                sources = format_sources(nodes) if nodes else ""

            except anthropic.OverloadedError:
                log.warning("Anthropic overloaded — all retries exhausted")
                await message.reply("Anthropic is busy, try again in a moment.")
                return
            except Exception:
                log.exception("RAG pipeline failed")
                await message.reply("Something went wrong answering that.")
                return

        await send_answer(message, answer, sources)

    except Exception:
        log.exception("Message handling failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Register every slash command module
    knowledge.setup(tree)
    status.setup(tree)
    glossary.setup(tree)
    thread_mode_cmd.setup(tree)
    archive_thread.setup(tree)
    export_single.setup(tree)
    export_all.setup(tree)
    export_state.setup(tree)
    export_thread.setup(tree)

    # Build the vector retriever and store it in shared globals so all
    # modules that call retrieve_context() have access
    G.retriever = build_retriever()
    log.info("Retriever ready")

    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
