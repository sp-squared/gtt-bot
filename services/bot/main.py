import os
import logging
import asyncio

import discord

from llama_index.core import VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OLLAMA_HOST = os.environ["OLLAMA_HOST"]
QDRANT_HOST = os.environ["QDRANT_HOST"]
LLM_MODEL = os.environ["LLM_MODEL"]
EMBED_MODEL = os.environ["EMBED_MODEL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]
TOP_K = int(os.environ.get("TOP_K", "5"))

DISCORD_MSG_LIMIT = 2000


def build_query_engine():
    Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL, base_url=OLLAMA_HOST)
    Settings.llm = Ollama(model=LLM_MODEL, base_url=OLLAMA_HOST, request_timeout=120.0)

    client = QdrantClient(url=QDRANT_HOST)
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION)
    index = VectorStoreIndex.from_vector_store(vector_store)
    return index.as_query_engine(similarity_top_k=TOP_K)


intents = discord.Intents.default()
intents.message_content = True
intents.guild_messages = True

client = discord.Client(intents=intents)
query_engine = None


@client.event
async def on_ready():
    log.info("Logged in as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if client.user not in message.mentions:
        return

    question = message.clean_content.replace(f"@{client.user.name}", "").strip()
    if not question:
        return

    async with message.channel.typing():
        try:
            response = await asyncio.to_thread(query_engine.query, question)
            answer = str(response).strip() or "(no answer)"
        except Exception:
            log.exception("Query failed")
            await message.reply("Something went wrong answering that.")
            return

    for i in range(0, len(answer), DISCORD_MSG_LIMIT):
        await message.reply(answer[i : i + DISCORD_MSG_LIMIT])


def main():
    global query_engine
    query_engine = build_query_engine()
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
