# GTT Vault → Hermes Agent (MCP Integration)

Exposes the GTT knowledge base as an MCP tool server so Hermes Agent
can search the Obsidian vault from VS Code, CLI, Telegram, or any
other Hermes interface.

## Prerequisites

- GTT Bot stack running (`docker compose up -d`) — Ollama and Qdrant
  must be reachable on localhost
- Hermes Agent installed (`hermes doctor` passes)
- Python 3.11+ with a venv for the MCP server

## 1. Set up the MCP server environment

```bash
cd /path/to/gtt-bot/services/mcp
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Verify it can reach Ollama + Qdrant

```bash
# These should both respond (your Docker stack must be running)
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:6333/collections
```

## 3. Test the MCP server standalone

```bash
cd /path/to/gtt-bot/services/mcp
source .venv/bin/activate
python gtt_mcp_server.py
# Should print "Retriever ready" then wait for stdio input.
# Ctrl+C to exit.
```

## 4. Register with Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  gtt_vault:
    command: "/path/to/gtt-bot/services/mcp/.venv/bin/python"
    args: ["/path/to/gtt-bot/services/mcp/gtt_mcp_server.py"]
```

Replace `/path/to/gtt-bot` with your actual path.

On Windows, use the full `.venv\Scripts\python.exe` path:

```yaml
mcp_servers:
  gtt_vault:
    command: "C:/Users/colin/path/to/gtt-bot/services/mcp/.venv/Scripts/python.exe"
    args: ["C:/Users/colin/path/to/gtt-bot/services/mcp/gtt_mcp_server.py"]
```

## 5. Verify in Hermes

```bash
hermes
```

Then ask:

```
Search the GTT vault for "engineering mentorship"
```

Hermes should discover `search_gtt_vault` and `list_gtt_topics` as
available tools and call them when relevant.

To force-reload after config changes:

```
/reload-mcp
```

## How it works

```
Hermes Agent (VS Code / CLI / Telegram)
    │
    │  stdio (MCP protocol)
    ▼
gtt_mcp_server.py
    │
    ├──► Ollama (127.0.0.1:11434)  — query embedding
    │
    └──► Qdrant (127.0.0.1:6333)   — vector search
```

The MCP server imports the same retriever code the Discord bot uses.
It talks directly to the Ollama and Qdrant containers already running
in your Docker Compose stack. No extra services needed.

## Tools exposed

| Tool               | Description                                     |
|--------------------|-------------------------------------------------|
| `search_gtt_vault` | Hybrid search (vector + keyword) over the vault |
| `list_gtt_topics`  | List all topic names from the indexed vault      |

## Notes

- The Docker stack must be running for the MCP server to work.
  Ollama and Qdrant are the actual backends.
- The MCP server is read-only — it searches the vault but never
  writes to it. The indexer service handles ingestion.
- If you add new notes to the vault, the indexer auto-reindexes.
  The MCP server picks up changes on the next query (it reads
  from Qdrant at query time, not from a cached snapshot).
- Environment defaults are set inside the script. Override them
  in the Hermes config `env:` block if your ports differ.
