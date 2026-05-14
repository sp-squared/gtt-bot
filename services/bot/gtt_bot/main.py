import asyncio
import logging
import time

import discord
from discord import app_commands

import gtt_bot.globals as G
from gtt_bot.automod.rules import check_automod
from gtt_bot.commands import archive_thread, export_all, export_single, export_state, export_thread, glossary, knowledge, status, thread_mode_cmd
from gtt_bot.thread_store import load as load_thread_store, register as register_thread
from gtt_bot.config import (
    COOLDOWN_ANTHROPIC,
    DISCORD_MSG_LIMIT,
    COOLDOWN_EXEMPT_USERS,
    DISCORD_TOKEN,
    MAX_QUESTION_LENGTH,
    MOD_CHANNEL_ID,
    REQUIRED_ROLE,
    THREAD_HISTORY_LIMIT,
)
from gtt_bot.discord_utils.cooldown import check_cooldown
from gtt_bot.discord_utils.permissions import has_required_role, is_allowed_channel, is_allowed_guild
from gtt_bot.discord_utils.thread_history import get_thread_history
from gtt_bot.discord_utils.thread_mode import get_thread_mode
from gtt_bot.rag.anthropic import query_anthropic
from gtt_bot.rag.formatters import format_sources, split_at_sentence
from gtt_bot.rag.retriever import build_retriever, retrieve_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.guild_messages = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Register all slash commands
knowledge.setup(tree)
status.setup(tree)
archive_thread.setup(tree)
thread_mode_cmd.setup(tree)
export_single.setup(tree)
export_all.setup(tree)
export_state.setup(tree)
export_thread.setup(tree)
glossary.setup(tree)


async def _send_answer(message: discord.Message, answer: str, sources: str = ""):
    chunks = split_at_sentence(answer)

    use_threads = get_thread_mode(message.guild.id) if message.guild else False
    if use_threads and isinstance(message.channel, discord.TextChannel):
        thread = await message.create_thread(name=message.clean_content[:80] or "GTT Bot")
        register_thread(thread.id, message.author.id)
        for chunk in chunks:
            await thread.send(chunk)
        if sources:
            await thread.send(sources)
    else:
        for chunk in chunks:
            await message.reply(chunk)
        if sources:
            await message.reply(sources)


@client.event
async def on_ready():
    await tree.sync()
    log.info("Slash commands synced")
    log.info("Logged in as %s", client.user)
    if REQUIRED_ROLE:
        log.info("API access restricted to role: %s", REQUIRED_ROLE)
    if MOD_CHANNEL_ID:
        log.info("Automod alerts → channel %s", MOD_CHANNEL_ID)


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if isinstance(message.author, discord.Member) and message.author.bot:
        return

    if message.guild:
        await check_automod(message)

    if client.user not in message.mentions:
        return
    if message.guild and not is_allowed_guild(message.guild.id):
        return
    if not is_allowed_channel(message.channel):
        return
    if message.guild and not has_required_role(message.author):
        await message.reply(f"You need the **{REQUIRED_ROLE}** role to use this.", delete_after=10)
        return

    question = message.clean_content.replace(f"@{client.user.name}", "").strip()
    if not question:
        return
    if len(question) > MAX_QUESTION_LENGTH:
        await message.reply(f"Keep it under {MAX_QUESTION_LENGTH} characters.")
        return

    if message.author.id not in COOLDOWN_EXEMPT_USERS:
        remaining = check_cooldown(message.author.id, G.anthropic_cooldowns, COOLDOWN_ANTHROPIC)
        if remaining > 0:
            await message.reply(f"Slow down — you can ask again in {int(remaining) + 1}s.", delete_after=5)
            return
        G.anthropic_cooldowns[message.author.id] = time.time()

    try:
        async with message.channel.typing():
            try:
                nodes = await asyncio.to_thread(retrieve_context, question)
                history = await get_thread_history(message.channel, client, limit=THREAD_HISTORY_LIMIT)

                if not nodes:
                    answer = await asyncio.to_thread(query_anthropic, question, "", history)
                    sources = ""
                else:
                    context = "\n\n".join(n.get_content() for n in nodes)
                    answer = await asyncio.to_thread(query_anthropic, question, context, history)
                    sources = format_sources(nodes)
            except Exception:
                log.exception("Query failed")
                await message.reply("Something went wrong answering that.")
                return
        await _send_answer(message, answer, sources)
    except Exception:
        log.exception("Message handling failed")


def main():
    load_thread_store()
    G.retriever = build_retriever()
    log.info("Retriever ready")
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
