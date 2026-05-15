"""
GTT Vault MCP Server (standalone)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Searches the GTT knowledge base via direct HTTP calls to Ollama and Qdrant.
No LlamaIndex dependency, no gtt_bot imports. Works with any Python 3.10+.

Usage:
    python gtt_mcp_server.py
"""

import asyncio
import json
import logging
import os
import re

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gtt-mcp")

# ---------------------------------------------------------------------------
# Config — defaults match docker-compose.yml localhost bindings
# ---------------------------------------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "http://127.0.0.1:6333")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "vault")
TOP_K = int(os.environ.get("TOP_K", "5"))
MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.40"))
KEYWORD_WEIGHT = float(os.environ.get("KEYWORD_WEIGHT", "0.5"))

# ---------------------------------------------------------------------------
# Embedding via Ollama HTTP API
# ---------------------------------------------------------------------------

async def embed_query(text: str) -> list[float]:
    """Get embedding vector from Ollama."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


# ---------------------------------------------------------------------------
# Qdrant search via HTTP API
# ---------------------------------------------------------------------------

class ChunkResult:
    __slots__ = ("file_name", "content", "vector_score", "keyword_score", "score")

    def __init__(self, file_name: str, content: str, vector_score: float):
        self.file_name = file_name
        self.content = content
        self.vector_score = vector_score
        self.keyword_score = 0.0
        self.score = 0.0


async def search_qdrant(vector: list[float], limit: int = 100) -> list[ChunkResult]:
    """Search Qdrant collection and parse LlamaIndex-format payloads."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{QDRANT_HOST}/collections/{COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "with_payload": True,
            },
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])

    chunks = []
    for point in results:
        payload = point.get("payload", {})
        score = point.get("score", 0.0)

        # LlamaIndex stores content in _node_content as a JSON string
        raw = payload.get("_node_content", "")
        if not raw:
            continue
        try:
            node_data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        content = node_data.get("text", "")
        metadata = node_data.get("metadata", {})
        file_name = metadata.get("file_name", "unknown.md")

        if not content.strip():
            continue

        chunks.append(ChunkResult(
            file_name=file_name,
            content=content.strip(),
            vector_score=score,
        ))
    return chunks


# ---------------------------------------------------------------------------
# Hybrid scoring (ported from gtt_bot/rag/retriever.py)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "on", "at", "by", "for", "with", "about", "as", "into", "through",
    "during", "before", "after", "and", "or", "but", "if", "then", "than",
    "so", "yet", "not", "no", "nor", "how", "what", "when", "where", "who",
    "which", "why", "this", "that", "these", "those", "it", "its", "me",
    "my", "you", "your", "he", "she", "we", "they", "them", "their",
    "our", "us", "tell", "explain", "give", "get", "go", "know", "think",
    "use", "make", "need",
})

_GTT_KEYWORDS = frozenset({
    "dif", "rlr", "merly", "mentor", "deterministic", "stochastic",
    "folding", "vibe", "lifetime", "ownership", "deficit", "blast",
})


def _significant_terms(query: str) -> list[str]:
    terms = []
    for w in re.findall(r"\b\w+\b", query):
        if w.isupper() and len(w) >= 2:
            terms.append(w.lower())
        elif len(w) >= 4 and w.lower() not in _STOP_WORDS:
            terms.append(w.lower())
    return list(dict.fromkeys(terms))


def _keyword_score(terms: list[str], text: str, filename: str = "") -> float:
    if not terms:
        return 0.0
    text_lower = text.lower()
    fname_words = re.findall(r"\w+", filename.replace(".md", "")) if filename else []
    fname_text = " ".join(fname_words).lower()
    fname_initials = "".join(w[0] for w in fname_words).lower() if fname_words else ""

    content_matches = sum(
        1 for t in terms if re.search(r"\b" + re.escape(t) + r"\b", text_lower)
    )
    fname_matches = 0
    for t in terms:
        if re.search(r"\b" + re.escape(t) + r"\b", fname_text):
            fname_matches += 1
        elif len(t) >= 2 and fname_initials == t.lower():
            fname_matches += 1

    return 0.2 * (content_matches / len(terms)) + 0.8 * (fname_matches / len(terms))


def hybrid_rank(chunks: list[ChunkResult], query: str) -> list[ChunkResult]:
    """Re-rank chunks using blended vector + keyword scoring, dedupe by file."""
    terms = _significant_terms(query)
    vector_weight = 1.0 - KEYWORD_WEIGHT

    if terms:
        for c in chunks:
            k = _keyword_score(terms, c.content, c.file_name)
            c.keyword_score = round(k, 4)
            c.score = vector_weight * c.vector_score + KEYWORD_WEIGHT * k
    else:
        for c in chunks:
            c.score = c.vector_score

    chunks.sort(key=lambda c: c.score, reverse=True)

    # Deduplicate by file — keep highest scoring chunk per file
    seen: dict[str, ChunkResult] = {}
    for c in chunks:
        if c.file_name not in seen or c.score > seen[c.file_name].score:
            seen[c.file_name] = c
    ranked = list(seen.values())
    ranked.sort(key=lambda c: c.score, reverse=True)

    results = [c for c in ranked[:TOP_K] if c.score >= MIN_SCORE]

    # GTT fallback: lower threshold for GTT-specific terms
    if not results and set(terms) & _GTT_KEYWORDS:
        fallback_threshold = round(MIN_SCORE * 0.75, 3)
        results = [c for c in ranked[:TOP_K] if c.score >= fallback_threshold]

    return results


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_summary(chunks: list[ChunkResult]) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        stem = c.file_name.replace(".md", "")
        content_lines = c.content.splitlines()
        if content_lines and content_lines[0].strip() == stem:
            content_lines = content_lines[1:]
        text = "\n".join(content_lines).strip()
        first_sentence = text.split(".")[0].strip() + "."
        match_tag = " — 100% match" if c.keyword_score >= 1.0 else ""
        lines.append(f"[{i}] {c.file_name} ({c.score:.2f}){match_tag}\n{first_sentence}")
    return "\n\n".join(lines)


def format_raw(chunks: list[ChunkResult]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        stem = c.file_name.replace(".md", "")
        content_lines = c.content.splitlines()
        if content_lines and content_lines[0].strip() == stem:
            content_lines = content_lines[1:]
        text = "\n".join(content_lines).strip()
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())
        match_tag = " — 100% match" if c.keyword_score >= 1.0 else ""
        parts.append(f"[{i}] {c.file_name}{match_tag}\n{quoted}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Vault topic listing
# ---------------------------------------------------------------------------

async def list_vault_topics() -> list[str]:
    """Get all unique filenames from the Qdrant collection."""
    filenames: set[str] = set()
    offset = None
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            body: dict = {"limit": 100, "with_payload": True}
            if offset is not None:
                body["offset"] = offset
            resp = await client.post(
                f"{QDRANT_HOST}/collections/{COLLECTION}/points/scroll",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json().get("result", {})
            points = data.get("points", [])
            for point in points:
                raw = point.get("payload", {}).get("_node_content", "")
                if not raw:
                    continue
                try:
                    fname = json.loads(raw).get("metadata", {}).get("file_name", "")
                except (json.JSONDecodeError, TypeError):
                    continue
                if fname:
                    filenames.add(fname)
            offset = data.get("next_page_offset")
            if offset is None:
                break
    return sorted(f.removesuffix(".md").replace("-", " ") for f in filenames)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

app = Server("gtt-vault")


@app.list_tools()
async def handle_list_tools():
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
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    if name == "search_gtt_vault":
        query = arguments.get("query", "").strip()
        if not query:
            return [TextContent(type="text", text="Empty query — provide search terms.")]

        try:
            vector = await embed_query(query)
            raw_chunks = await search_qdrant(vector, limit=min(100, TOP_K * 20))
            results = hybrid_rank(raw_chunks, query)
        except httpx.ConnectError as e:
            return [TextContent(type="text", text=f"Cannot reach backend services. Is Docker running?\n{e}")]
        except Exception as e:
            log.exception("Search failed")
            return [TextContent(type="text", text=f"Search failed: {e}")]

        if not results:
            return [TextContent(type="text", text=f"No results for '{query}'.")]

        summary = format_summary(results)
        raw = format_raw(results)
        sources = ", ".join(c.file_name for c in results)

        return [TextContent(
            type="text",
            text=(
                f"## GTT Vault — {len(results)} results for '{query}'\n\n"
                f"**Sources:** {sources}\n\n"
                f"### Summary\n\n{summary}\n\n"
                f"---\n\n"
                f"### Raw chunks\n\n{raw}"
            ),
        )]

    if name == "list_gtt_topics":
        try:
            topics = await list_vault_topics()
        except httpx.ConnectError as e:
            return [TextContent(type="text", text=f"Cannot reach Qdrant. Is Docker running?\n{e}")]
        except Exception as e:
            log.exception("Topic listing failed")
            return [TextContent(type="text", text=f"Failed to list topics: {e}")]

        if not topics:
            return [TextContent(type="text", text="No topics found in the vault.")]

        topic_list = "\n".join(f"- {t}" for t in topics)
        return [TextContent(
            type="text",
            text=f"## GTT Vault Topics ({len(topics)} entries)\n\n{topic_list}",
        )]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    log.info("GTT Vault MCP Server starting")
    log.info("  Ollama: %s", OLLAMA_HOST)
    log.info("  Qdrant: %s", QDRANT_HOST)
    log.info("  Collection: %s", COLLECTION)

    # Verify backends are reachable before accepting connections
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{OLLAMA_HOST}/api/tags")
            await client.get(f"{QDRANT_HOST}/collections")
        log.info("Backend services reachable — ready")
    except httpx.ConnectError as e:
        log.error("Cannot reach backend services: %s", e)
        log.error("Make sure Docker Compose stack is running.")
        return

    async with stdio_server() as (read_stream, write_stream):
        init_options = app.create_initialization_options()
        await app.run(read_stream, write_stream, init_options)

if __name__ == "__main__":
    asyncio.run(main())
