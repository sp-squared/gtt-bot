"""
GTT Vault MCP Server
~~~~~~~~~~~~~~~~~~~~
Exposes the GTT knowledge base as MCP tools so Hermes Agent (or any
MCP client) can search the Obsidian vault via the same hybrid retrieval
pipeline the Discord bot uses.

Talks directly to Ollama (localhost:11434) and Qdrant (localhost:6333)
— no HTTP wrapper needed when running on the same machine.

Usage (stdio, for MCP client config):
    python gtt_mcp_server.py

Requires the same Python environment as the bot service.
"""

import asyncio
import os
import sys
import logging

# ---------------------------------------------------------------------------
# Environment setup — must happen before any gtt_bot imports because
# config.py reads os.environ at module level.  The MCP server only needs
# the retrieval stack, not Discord or Anthropic, so we set safe defaults
# for the env vars it *doesn't* use.
# ---------------------------------------------------------------------------

os.environ.setdefault("DISCORD_TOKEN", "unused-by-mcp")
os.environ.setdefault("ANTHROPIC_API_KEY", "unused-by-mcp")
os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:11434")
os.environ.setdefault("QDRANT_HOST", "http://127.0.0.1:6333")
os.environ.setdefault("EMBED_MODEL", "nomic-embed-text")
os.environ.setdefault("QDRANT_COLLECTION", "vault")
os.environ.setdefault("TOP_K", "5")

# Add the bot package to sys.path so gtt_bot is importable
_bot_dir = os.path.join(os.path.dirname(__file__), "..", "bot")
sys.path.insert(0, os.path.abspath(_bot_dir))

import gtt_bot.globals as G
from gtt_bot.rag.retriever import build_retriever, retrieve_context
from gtt_bot.rag.formatters import extractive_summary, format_raw_chunks_plain

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gtt-mcp")

# ---------------------------------------------------------------------------
# MCP server definition
# ---------------------------------------------------------------------------

app = Server("gtt-vault")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="search_gtt_vault",
            description=(
                "Search the GTT (Goju Tech Talk) knowledge base. Returns ranked "
                "chunks from an Obsidian vault covering engineering mentorship, "
                "DIF (Deterministic Intent Folding), RLR (Repository Lifetime "
                "Reasoning), vibe coding, critical thinking, data-oriented design, "
                "AI hype analysis, and related topics. Use specific terms rather "
                "than full questions — e.g. 'deterministic intent folding' not "
                "'what is DIF?'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms (e.g. 'engineering mentorship', 'vibe coding ownership', 'DIF vs LLM')",
                    }
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_gtt_topics",
            description=(
                "List all topic names available in the GTT knowledge base. "
                "Useful for discovering what the vault covers before searching."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "search_gtt_vault":
        query = arguments.get("query", "").strip()
        if not query:
            return [TextContent(type="text", text="Empty query — provide search terms.")]

        nodes = await asyncio.to_thread(retrieve_context, query)

        if not nodes:
            return [TextContent(type="text", text=f"No results for '{query}'.")]

        summary = extractive_summary(nodes)
        raw = format_raw_chunks_plain(nodes)
        sources = ", ".join(
            n.metadata.get("file_name", "?") for n in nodes
        )

        return [
            TextContent(
                type="text",
                text=(
                    f"## GTT Vault — {len(nodes)} results for '{query}'\n\n"
                    f"**Sources:** {sources}\n\n"
                    f"### Summary\n\n{summary}\n\n"
                    f"---\n\n"
                    f"### Raw chunks\n\n{raw}"
                ),
            )
        ]

    if name == "list_gtt_topics":
        if not G.query_terms:
            return [TextContent(type="text", text="No topics loaded yet.")]
        topic_list = "\n".join(f"- {t}" for t in G.query_terms)
        return [
            TextContent(
                type="text",
                text=f"## GTT Vault Topics ({len(G.query_terms)} entries)\n\n{topic_list}",
            )
        ]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    log.info("Building retriever (connecting to Ollama + Qdrant)...")
    G.retriever = build_retriever()
    log.info("Retriever ready — starting MCP stdio server")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
