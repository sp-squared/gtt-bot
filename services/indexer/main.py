import os
import re
import time
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import CreateAlias, CreateAliasOperation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("indexer")

VAULT_DIR = os.environ.get("VAULT_DIR", "/vault")
OLLAMA_HOST = os.environ["OLLAMA_HOST"]
QDRANT_HOST = os.environ["QDRANT_HOST"]
EMBED_MODEL = os.environ["EMBED_MODEL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]

DEBOUNCE_SECONDS = 3.0

FRONTMATTER_RE = re.compile(r"^\s*---[\s\S]*?---\s*$")


def is_noise_chunk(text: str) -> bool:
    """Return True for chunks that are pure YAML frontmatter or near-empty."""
    stripped = text.strip()
    if not stripped:
        return True
    # Pure frontmatter block
    if FRONTMATTER_RE.match(stripped):
        return True
    # Frontmatter with nothing else meaningful (under 30 chars after stripping --- blocks)
    without_fm = re.sub(r"---[\s\S]*?---", "", stripped).strip()
    if len(without_fm) < 30:
        return True
    return False


def _managed_physical_collections(client: QdrantClient, alias: str) -> list[str]:
    """Collections matching the indexer's physical naming scheme (alias_<ts>)."""
    prefix = f"{alias}_"
    return [c.name for c in client.get_collections().collections if c.name.startswith(prefix)]


def build_index():
    log.info("Building index from %s", VAULT_DIR)

    Settings.embed_model = OllamaEmbedding(
        model_name=EMBED_MODEL, base_url=OLLAMA_HOST
    )
    Settings.node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    client = QdrantClient(url=QDRANT_HOST)

    # Build into a freshly named physical collection. The alias COLLECTION is
    # swapped to point at it at the end — readers querying via the alias see
    # the previous index until the swap, so there is no unavailability window.
    new_collection = f"{COLLECTION}_{int(time.time())}"

    vector_store = QdrantVectorStore(client=client, collection_name=new_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    docs = SimpleDirectoryReader(
        VAULT_DIR, recursive=True, required_exts=[".md"]
    ).load_data()

    log.info("Loaded %d markdown documents", len(docs))

    parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)
    nodes = parser.get_nodes_from_documents(docs)
    clean_nodes = [n for n in nodes if not is_noise_chunk(n.get_content())]

    log.info("Indexing %d/%d chunks into %s (filtered %d noise chunks)",
             len(clean_nodes), len(nodes), new_collection, len(nodes) - len(clean_nodes))

    VectorStoreIndex(clean_nodes, storage_context=storage_context)

    # Legacy migration: if a literal collection named COLLECTION still exists
    # from before alias swap was introduced, drop it — Qdrant aliases and
    # collection names share a namespace, so we can't create the alias while
    # a collection of the same name occupies it.
    existing_names = {c.name for c in client.get_collections().collections}
    if COLLECTION in existing_names:
        log.info("Removing legacy literal collection %s", COLLECTION)
        client.delete_collection(collection_name=COLLECTION)

    # Atomically (re)point the public alias at the freshly built collection.
    client.update_aliases(change_aliases_operations=[
        CreateAliasOperation(
            create_alias=CreateAlias(
                collection_name=new_collection,
                alias_name=COLLECTION,
            )
        )
    ])
    log.info("Alias %s -> %s", COLLECTION, new_collection)

    # Garbage-collect prior physical collections we built. Safe because the
    # alias now points at new_collection, so nothing else references them.
    for name in _managed_physical_collections(client, COLLECTION):
        if name != new_collection:
            client.delete_collection(collection_name=name)
            log.info("Deleted stale collection %s", name)

    log.info("Index build complete (alias=%s, collection=%s)", COLLECTION, new_collection)


class DebouncedReindex(FileSystemEventHandler):
    def __init__(self):
        self._last_event = 0.0
        self._pending = False

    def on_any_event(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".md"):
            return
        self._last_event = time.time()
        self._pending = True

    def tick(self):
        if self._pending and (time.time() - self._last_event) >= DEBOUNCE_SECONDS:
            self._pending = False
            try:
                build_index()
            except Exception:
                log.exception("Reindex failed")


def main():
    Path(VAULT_DIR).mkdir(parents=True, exist_ok=True)

    # Initial build
    while True:
        try:
            build_index()
            break
        except Exception:
            log.exception("Initial index failed; retrying in 10s")
            time.sleep(10)

    handler = DebouncedReindex()
    observer = Observer()
    observer.schedule(handler, VAULT_DIR, recursive=True)
    observer.start()
    log.info("Watching %s for changes", VAULT_DIR)

    try:
        while True:
            time.sleep(1)
            handler.tick()
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
