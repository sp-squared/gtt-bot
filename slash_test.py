"""
Slash command integration tester.
Runs retrieval + formatting for every autocomplete term and every glossary entry.

    docker compose exec -it bot python slash_test.py

Pass --verbose to print full output for each result.
Pass --query "some term" to test a single query.
"""
import os, sys, argparse
sys.path.insert(0, "/app")
os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import logging
logging.disable(logging.CRITICAL)

from llama_index.core import VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from gtt_bot.config import (
    OLLAMA_HOST, QDRANT_HOST, EMBED_MODEL, COLLECTION,
    TOP_K, MIN_SCORE, KEYWORD_WEIGHT, GTT_GLOSSARY,
)
from gtt_bot.rag.retriever import _significant_terms, _keyword_score, _build_query_terms
from gtt_bot.rag.formatters import extractive_summary, format_raw_chunks_plain

import gtt_bot.globals as G

# ── bootstrap ────────────────────────────────────────────────────────────────

print("Initialising...", end=" ", flush=True)
Settings.llm = None
Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL, base_url=OLLAMA_HOST)
client = QdrantClient(url=QDRANT_HOST)
total = client.get_collection(COLLECTION).points_count or TOP_K * 4
retriever = VectorStoreIndex.from_vector_store(
    QdrantVectorStore(client=client, collection_name=COLLECTION)
).as_retriever(similarity_top_k=min(int(total), 500))
G.query_terms = _build_query_terms(client, COLLECTION)
print(f"ready ({total} chunks, {len(G.query_terms)} terms)\n")

VW = 1.0 - KEYWORD_WEIGHT


def retrieve(query: str) -> list:
    nodes = retriever.retrieve(query)
    terms = _significant_terms(query)
    if terms:
        for node in nodes:
            v = node.score or 0.0
            fname = node.metadata.get("file_name", "")
            k = _keyword_score(terms, node.get_content(), fname)
            node.metadata["_vector_score"] = round(v, 4)
            node.metadata["_keyword_score"] = round(k, 4)
            node.score = VW * v + KEYWORD_WEIGHT * k
        nodes.sort(key=lambda n: n.score or 0, reverse=True)
    seen: dict = {}
    for node in nodes:
        fname = node.metadata.get("file_name", node.node_id)
        if fname not in seen or (node.score or 0) > (seen[fname].score or 0):
            seen[fname] = node
    ranked = list(seen.values())
    return [n for n in ranked[:TOP_K] if (n.score or 0) >= MIN_SCORE]


# ── test runner ───────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--verbose", action="store_true")
parser.add_argument("--query", default=None)
args = parser.parse_args()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m~\033[0m"

results = {"pass": 0, "empty": 0, "error": 0}

def run_query(label: str, query: str):
    try:
        nodes = retrieve(query)
        if not nodes:
            print(f"  {WARN}  EMPTY   {label!r}")
            results["empty"] += 1
            return
        has_perfect = any(n.metadata.get("_keyword_score", 0) >= 1.0 for n in nodes)
        top = nodes[0]
        top_file = top.metadata.get("file_name", "?")
        top_score = top.score or 0
        tag = " [100% match]" if has_perfect else ""
        print(f"  {PASS}  {top_score:.3f}  {top_file}{tag}  ← {label!r}")
        if args.verbose:
            print(extractive_summary(nodes))
            print(format_raw_chunks_plain(nodes))
            print()
        results["pass"] += 1
    except Exception as e:
        print(f"  {FAIL}  ERROR   {label!r}  — {e}")
        results["error"] += 1


if args.query:
    print(f"── single query ─────────────────────────────────────────")
    run_query(args.query, args.query)
else:
    # /knowledge-base and /knowledge-search share the same retrieval path
    print(f"── /knowledge-base + /knowledge-search ({len(G.query_terms)} autocomplete terms) ──")
    for term in G.query_terms:
        run_query(term, term)

    print(f"\n── /glossary ({len(GTT_GLOSSARY)} entries) ───────────────────────────────")
    for entry in GTT_GLOSSARY:
        # glossary itself has no retrieval — just verify the example query it suggests
        run_query(entry["term"], entry["example"].replace("/knowledge-search ", "").replace("@GTT Bot ", ""))

print(f"\n── results ──────────────────────────────────────────────────")
print(f"  pass : {results['pass']}")
print(f"  empty: {results['empty']}")
print(f"  error: {results['error']}")
print(f"  total: {sum(results.values())}")
