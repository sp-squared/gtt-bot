import json
import logging
import re
import time

from llama_index.core import VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

import gtt_bot.globals as G
from gtt_bot.config import OLLAMA_HOST, QDRANT_HOST, EMBED_MODEL, COLLECTION, TOP_K, MIN_SCORE, KEYWORD_WEIGHT

log = logging.getLogger("bot")

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall", "should",
    "may", "might", "must", "can", "could", "to", "of", "in", "on", "at", "by",
    "for", "with", "about", "as", "into", "through", "during", "before", "after",
    "and", "or", "but", "if", "then", "than", "so", "yet",
    "not", "no", "nor", "how", "what", "when", "where", "who", "which", "why",
    "this", "that", "these", "those", "it", "its", "me", "my", "you", "your",
    "he", "she", "we", "they", "them", "their", "our", "us",
    "tell", "explain", "give", "get", "go", "know", "think", "use", "make", "need",
})

# GTT-specific terms that trigger the fallback retrieval pass
_GTT_KEYWORDS = frozenset({
    "dif", "rlr", "merly", "mentor",
    "deterministic", "stochastic", "folding",
    "vibe", "lifetime", "ownership", "deficit", "blast",
})


def _significant_terms(query: str) -> list[str]:
    """Extract meaningful search terms: preserve acronyms (DIF, RLR), filter noise words."""
    terms = []
    for w in re.findall(r'\b\w+\b', query):
        if w.isupper() and len(w) >= 2:        # acronyms: DIF, RLR, LLM, AI
            terms.append(w.lower())
        elif len(w) >= 4 and w.lower() not in _STOP_WORDS:
            terms.append(w.lower())
    return list(dict.fromkeys(terms))           # deduplicate, preserve order


def _keyword_score(terms: list[str], text: str, filename: str = "") -> float:
    if not terms:
        return 0.0

    text_lower = text.lower()
    fname_words = re.findall(r'\w+', filename.replace('.md', '')) if filename else []
    fname_text = ' '.join(fname_words).lower()
    # Initials of filename words — lets "dif" match "deterministic-intent-folding.md"
    fname_initials = ''.join(w[0] for w in fname_words).lower() if fname_words else ''

    content_matches = sum(
        1 for t in terms if re.search(r'\b' + re.escape(t) + r'\b', text_lower)
    )
    fname_matches = 0
    for t in terms:
        if re.search(r'\b' + re.escape(t) + r'\b', fname_text):
            fname_matches += 1
        elif len(t) >= 2 and fname_initials == t.lower():
            # Acronym match: "dif" → initials of "deterministic-intent-folding"
            fname_matches += 1

    # Filename match is a much stronger relevance signal than content mention.
    # A file whose name encodes the topic IS the authoritative source; a file that
    # merely mentions the topic is supporting context.
    return 0.2 * (content_matches / len(terms)) + 0.8 * (fname_matches / len(terms))


def _is_gtt_question(terms: list[str]) -> bool:
    return bool(set(terms) & _GTT_KEYWORDS)


def _build_query_terms(client, collection: str) -> list[str]:
    """Derive autocomplete terms from vault filenames stored in Qdrant.

    Returns ALL vault filenames ranked by chunk count (most-covered topics first).
    The autocomplete handler applies Discord's 25-choice cap after filtering,
    so keeping the full pool here maximises how many useful choices appear
    when a user types a partial query.
    """
    chunk_counts: dict[str, int] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            with_payload=True,
            limit=100,
            offset=offset,
        )
        for point in points:
            raw = point.payload.get("_node_content", "")
            if not raw:
                continue
            try:
                fname = json.loads(raw).get("metadata", {}).get("file_name", "")
            except (json.JSONDecodeError, TypeError):
                continue
            if fname:
                chunk_counts[fname] = chunk_counts.get(fname, 0) + 1
        if offset is None:
            break

    # Sort by chunk count descending — files with more chunks are more
    # thoroughly documented and therefore higher-value autocomplete targets.
    ranked = sorted(chunk_counts.items(), key=lambda x: x[1], reverse=True)
    return [
        fname.removesuffix(".md").replace("-", " ")
        for fname, _ in ranked
    ]


def build_retriever():
    Settings.llm = None  # Prevent accidental OpenAI calls
    Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL, base_url=OLLAMA_HOST)
    client = QdrantClient(url=QDRANT_HOST)
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION)
    index = VectorStoreIndex.from_vector_store(vector_store)
    # Fetch the entire collection so hybrid keyword scoring can surface files
    # whose content uses acronyms (e.g. "DIF") but whose filename contains the full term.
    # For large corpora this caps at 500 to stay performant.
    # Wait for the indexer to finish — retries up to 30s before falling back
    total = 0
    for attempt in range(20):
        try:
            total = client.get_collection(COLLECTION).points_count or 0
            if total > 0:
                break
        except Exception:
            pass
        log.info("Waiting for index to be ready (attempt %d/20)...", attempt + 1)
        time.sleep(3)
    k = min(int(total), 500) if total else TOP_K * 4
    retriever = index.as_retriever(similarity_top_k=k)

    try:
        from gtt_bot.config import GTT_QUERY_TERMS
        G.query_terms = _build_query_terms(client, COLLECTION) or GTT_QUERY_TERMS
        log.info("Query terms loaded: %d terms from vault", len(G.query_terms))
    except Exception:
        log.exception("Failed to build query terms from vault; using static fallback")

    log.info("Vector retriever ready (k=%d, dedup to %d unique files)", k, TOP_K)
    return retriever


def retrieve_context(question: str) -> list:
    nodes = G.retriever.retrieve(question)

    # Hybrid scoring: blend vector similarity with keyword match for exact terms
    terms = _significant_terms(question)
    vector_weight = 1.0 - KEYWORD_WEIGHT
    if terms:
        for node in nodes:
            v = node.score or 0.0
            fname = node.metadata.get("file_name", "")
            k = _keyword_score(terms, node.get_content(), fname)
            node.metadata["_vector_score"] = round(v, 4)
            node.metadata["_keyword_score"] = round(k, 4)
            node.score = vector_weight * v + KEYWORD_WEIGHT * k
        nodes.sort(key=lambda n: n.score or 0, reverse=True)

    # Deduplicate by source file — keep highest scoring chunk per file
    seen_files: dict = {}
    for node in nodes:
        fname = node.metadata.get("file_name", node.node_id)
        if fname not in seen_files or (node.score or 0) > (seen_files[fname].score or 0):
            seen_files[fname] = node

    ranked = list(seen_files.values())
    results = [n for n in ranked[:TOP_K] if (n.score or 0) >= MIN_SCORE]

    if results:
        return results

    # GTT fallback: lower threshold by 25% for GTT-specific questions so that
    # correction-style phrasings ("isn't DIF just...") can still surface vault docs.
    if _is_gtt_question(terms):
        fallback_threshold = round(MIN_SCORE * 0.75, 3)
        fallback = [n for n in ranked[:TOP_K] if (n.score or 0) >= fallback_threshold]
        if fallback:
            log.info(
                "retrieve_context: GTT fallback triggered (best=%.3f, threshold=%.3f) for %r",
                fallback[0].score or 0,
                fallback_threshold,
                question[:80],
            )
            return fallback

    best = ranked[0].score if ranked else 0.0
    log.info(
        "retrieve_context: low confidence (best=%.3f, threshold=%.3f) for %r",
        best,
        MIN_SCORE,
        question[:80],
    )
    return []
