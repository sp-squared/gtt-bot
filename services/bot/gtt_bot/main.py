import os
import logging
import asyncio
import time

import discord
from discord import app_commands
import anthropic

from llama_index.core import VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OLLAMA_HOST = os.environ["OLLAMA_HOST"]
QDRANT_HOST = os.environ["QDRANT_HOST"]
EMBED_MODEL = os.environ["EMBED_MODEL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TOP_K = int(os.environ.get("TOP_K", "5"))

ALLOWED_CHANNELS = set(
    int(x.strip()) for x in os.environ.get("ALLOWED_CHANNELS", "").split(",") if x.strip()
)
ALLOWED_GUILDS = set(
    int(x.strip()) for x in os.environ.get("ALLOWED_GUILDS", "").split(",") if x.strip()
)
COOLDOWN_ANTHROPIC = int(os.environ.get("COOLDOWN_SECONDS", "30"))
COOLDOWN_LOCAL = int(os.environ.get("COOLDOWN_LOCAL_SECONDS", "10"))
MAX_QUESTION_LENGTH = int(os.environ.get("MAX_QUESTION_LENGTH", "500"))

# Default thread mode from env — can be toggled per-guild at runtime via /thread-mode
_DEFAULT_USE_THREADS = os.environ.get("USE_THREADS", "false").lower() == "true"

DISCORD_MSG_LIMIT = 2000

SYSTEM_PROMPT = """You are the GTT Bot, the AI assistant for Goju Tech Talk (GTT) — a community built around honest tech analysis, deep critical thinking, and the truth about AI, software engineering, and the future of programming.

You were built by the GTT community using a knowledge graph of atomic notes representing Goju's actual positions.

You are NOT a generic helpful assistant. You are a technically grounded, intellectually honest voice shaped by a specific worldview. Act like it.

## Core Worldview

You reason from these core positions:

1. AI Hype vs Reality — AI hype is structural, not accidental. It serves financial interests. LLMs are pattern-matching engines: genuinely useful in narrow ways, dangerously overstated in broad claims. Be accurate about AI, not anti-AI.

2. Deterministic Intent Folding (DIF) — DIF is Merly's own ML technology: deterministic, up to 1,000,000x faster than LLMs for specific tasks, and runs entirely locally. It is NOT a generic principle — it is a specific architecture that enables Repository Lifetime Reasoning (RLR), which is how Mentor detects vibe coded projects at scale. All major AI systems (Google, Meta, Microsoft, Apple) are stochastic and cannot replicate this.

3. Vibe Coding is Not Engineering — Using AI coding tools is fine. Shipping code you don't understand is abdication. DIF + RLR is the technical mechanism for detecting vibe coding by analyzing the full evolution of a repository, not just a snapshot.

4. Critical Thinking as Engineering Discipline — Critical thinking is a technical competency. Separate claim from evidence. Ask who benefits. Distinguish demo from production. Prefer falsification. Hold uncertainty explicitly.

5. Data-Oriented Design — Performance problems are usually data layout problems. Understanding how data moves through memory is a core engineering skill.

6. Tech Industry Analysis — Every company has an incentive structure. Understand it. No boosters, no reflexive cynics.

## Tone and Behavior

- Be direct. State your actual position.
- Be honest about uncertainty.
- Challenge lazy questions and surface hidden assumptions.
- Do not validate hype uncritically.
- Do not be contrarian for sport — the goal is accuracy.
- When DIF comes up, be precise: it is Merly's specific technology, not a generic design pattern.

## CRITICAL FORMATTING RULES — NEVER VIOLATE

- NEVER use numbered lists or bullet points.
- NEVER open with "To better understand", "To effectively", "Great question", "Certainly", or "Of course".
- ALWAYS respond in plain prose paragraphs only.
- NEVER end with "Would you like me to elaborate?" or similar.
- NEVER close with "By following these steps" or similar.

## Response Format

- Shorter is better. GTT people read.
- Lead with the honest take. Nuance after.
- Reference the knowledge base when relevant.
- No fluff. No "great question!", no "certainly!", no "as an AI language model..."
- Ask one clarifying question if genuinely ambiguous."""


def build_retriever():
    Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL, base_url=OLLAMA_HOST)
    client = QdrantClient(url=QDRANT_HOST)
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION)
    index = VectorStoreIndex.from_vector_store(vector_store)
    return index.as_retriever(similarity_top_k=TOP_K)


def retrieve_context(question: str) -> list:
    return retriever.retrieve(question)


def query_anthropic(question: str, context: str) -> str:
    ac = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "Context from the GTT knowledge base:\n"
        "---------------------\n"
        f"{context}\n"
        "---------------------\n"
        f"Question: {question}\n"
        "Answer: "
    )
    message = ac.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def extractive_summary(nodes: list) -> str:
    lines = []
    for i, node in enumerate(nodes, 1):
        content = node.get_content().strip()
        first_sentence = content.split(".")[0].strip() + "."
        source = node.metadata.get("file_name", f"chunk {i}")
        lines.append(f"**[{i}] {source}**\n{first_sentence}")
    return "\n\n".join(lines)


def format_raw_chunks(nodes: list) -> str:
    parts = []
    for i, node in enumerate(nodes, 1):
        source = node.metadata.get("file_name", f"chunk {i}")
        content = node.get_content().strip()
        parts.append(f"**[{i}] {source}**\n```\n{content}\n```")
    return "\n\n".join(parts)


def format_sources(nodes: list) -> str:
    seen = []
    for node in nodes:
        source = node.metadata.get("file_name", "unknown")
        if source not in seen:
            seen.append(source)
    return "**Sources:** " + " · ".join(f"`{s}`" for s in seen)


# --- Discord setup ---

intents = discord.Intents.default()
intents.message_content = True
intents.guild_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
retriever = None

# Index build time for /status
_start_time = time.time()

# Per-guild thread mode toggle — keys are guild IDs, values are bool
# Seeded from USE_THREADS env var for any guild not explicitly toggled
guild_thread_mode: dict[int, bool] = {}

anthropic_cooldowns: dict[int, float] = {}
local_cooldowns: dict[int, float] = {}


def check_cooldown(user_id: int, store: dict, seconds: int) -> float:
    now = time.time()
    remaining = seconds - (now - store.get(user_id, 0))
    return max(0.0, remaining)


def is_allowed_channel(channel_id: int) -> bool:
    return not ALLOWED_CHANNELS or channel_id in ALLOWED_CHANNELS


def is_allowed_guild(guild_id: int) -> bool:
    return not ALLOWED_GUILDS or guild_id in ALLOWED_GUILDS


def get_thread_mode(guild_id: int) -> bool:
    return guild_thread_mode.get(guild_id, _DEFAULT_USE_THREADS)


async def send_answer(message: discord.Message, answer: str, sources: str):
    """Send answer in a thread or inline depending on guild thread mode."""
    full = f"{answer}\n\n{sources}"
    use_threads = get_thread_mode(message.guild.id) if message.guild else False
    if use_threads and isinstance(message.channel, discord.TextChannel):
        thread = await message.create_thread(name=message.clean_content[:80] or "GTT Bot")
        for i in range(0, len(full), DISCORD_MSG_LIMIT):
            await thread.send(full[i : i + DISCORD_MSG_LIMIT])
    else:
        for i in range(0, len(full), DISCORD_MSG_LIMIT):
            await message.reply(full[i : i + DISCORD_MSG_LIMIT])


# --- Slash command: /knowledge-base ---

@tree.command(name="knowledge-base", description="Search the GTT vault directly (local, no API cost)")
@app_commands.describe(query="What do you want to look up in the knowledge base?")
async def knowledge_base(interaction: discord.Interaction, query: str):
    if not is_allowed_guild(interaction.guild_id):
        await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
        return

    if not is_allowed_channel(interaction.channel_id):
        await interaction.response.send_message("This command isn't enabled in this channel.", ephemeral=True)
        return

    if len(query) > MAX_QUESTION_LENGTH:
        await interaction.response.send_message(
            f"Query too long — keep it under {MAX_QUESTION_LENGTH} characters.", ephemeral=True
        )
        return

    remaining = check_cooldown(interaction.user.id, local_cooldowns, COOLDOWN_LOCAL)
    if remaining > 0:
        await interaction.response.send_message(
            f"Slow down — you can search again in {int(remaining) + 1}s.", ephemeral=True
        )
        return

    local_cooldowns[interaction.user.id] = time.time()
    await interaction.response.defer(ephemeral=True)

    try:
        nodes = await asyncio.to_thread(retrieve_context, query)

        if not nodes:
            await interaction.followup.send("Nothing found in the knowledge base for that query.")
            return

        summary = extractive_summary(nodes)
        raw = format_raw_chunks(nodes)

        summary_msg = f"**Knowledge Base — Summary**\n\n{summary}"
        raw_msg = f"**Knowledge Base — Raw Chunks**\n\n{raw}"

        await interaction.followup.send(summary_msg[:DISCORD_MSG_LIMIT])
        for i in range(0, len(raw_msg), DISCORD_MSG_LIMIT):
            await interaction.followup.send(raw_msg[i : i + DISCORD_MSG_LIMIT])

    except Exception:
        log.exception("knowledge-base command failed")
        await interaction.followup.send("Something went wrong with the lookup.")


# --- Slash command: /thread-mode ---

@tree.command(name="thread-mode", description="Toggle whether GTT Bot replies in threads or inline")
@app_commands.describe(enabled="Turn thread mode on or off")
@app_commands.choices(enabled=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def thread_mode(interaction: discord.Interaction, enabled: str):
    if not is_allowed_guild(interaction.guild_id):
        await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
        return

    state = enabled == "on"
    guild_thread_mode[interaction.guild_id] = state
    status = "on — bot will reply in threads" if state else "off — bot will reply inline"
    await interaction.response.send_message(f"Thread mode **{status}**.", ephemeral=True)
    log.info("Thread mode set to %s for guild %s by %s", state, interaction.guild_id, interaction.user)


# --- Slash command: /status ---

@tree.command(name="status", description="Show GTT Bot status and knowledge base info")
async def status(interaction: discord.Interaction):
    if not is_allowed_guild(interaction.guild_id):
        await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        from qdrant_client import QdrantClient as QC
        qc = QC(url=QDRANT_HOST)
        info = qc.get_collection(COLLECTION)
        vector_count = info.vectors_count or 0

        uptime_seconds = int(time.time() - _start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        thread_mode_str = "on" if get_thread_mode(interaction.guild_id) else "off"

        msg = (
            f"**GTT Bot — Status**\n\n"
            f"`Knowledge base` {vector_count} chunks indexed\n"
            f"`Embed model` {EMBED_MODEL}\n"
            f"`LLM` claude-sonnet-4-5 (Anthropic API)\n"
            f"`Thread mode` {thread_mode_str}\n"
            f"`Uptime` {uptime_str}\n"
            f"`Cooldown` {COOLDOWN_ANTHROPIC}s (mention) · {COOLDOWN_LOCAL}s (search)\n"
            f"`Max question` {MAX_QUESTION_LENGTH} chars"
        )
        await interaction.followup.send(msg)

    except Exception:
        log.exception("status command failed")
        await interaction.followup.send("Something went wrong fetching status.")


# --- @mention: full Anthropic pipeline ---

@client.event
async def on_ready():
    await tree.sync()
    log.info("Slash commands synced")
    log.info("Logged in as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if client.user not in message.mentions:
        return
    if message.guild and not is_allowed_guild(message.guild.id):
        return
    if not is_allowed_channel(message.channel.id):
        return

    question = message.clean_content.replace(f"@{client.user.name}", "").strip()
    if not question:
        return

    if len(question) > MAX_QUESTION_LENGTH:
        await message.reply(f"Keep it under {MAX_QUESTION_LENGTH} characters.")
        return

    remaining = check_cooldown(message.author.id, anthropic_cooldowns, COOLDOWN_ANTHROPIC)
    if remaining > 0:
        await message.reply(
            f"Slow down — you can ask again in {int(remaining) + 1}s.",
            delete_after=5,
        )
        return

    anthropic_cooldowns[message.author.id] = time.time()

    try:
        async with message.channel.typing():
            try:
                nodes = await asyncio.to_thread(retrieve_context, question)
                context = "\n\n".join(n.get_content() for n in nodes)
                answer = await asyncio.to_thread(query_anthropic, question, context)
                sources = format_sources(nodes)
            except Exception:
                log.exception("Query failed")
                await message.reply("Something went wrong answering that.")
                return

        await send_answer(message, answer, sources)

    except Exception:
        log.exception("Message handling failed")


def main():
    global retriever
    retriever = build_retriever()
    log.info("Retriever ready")
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()