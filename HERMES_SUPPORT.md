# Hermes Agent Integration

Connect [Hermes Agent](https://github.com/NousResearch/hermes-agent) to the GTT knowledge base via MCP (Model Context Protocol). This gives you personal access to the vault from Hermes CLI, VS Code, Discord, Telegram, or any other Hermes interface.

This is independent of the Discord bot — both read from the same Qdrant index, neither writes to it, and they never interfere with each other.

---

## How it works

```
Hermes Agent (CLI / VS Code / Discord / Telegram)
    │
    │  stdio (MCP protocol)
    ▼
gtt_mcp_server.py
    │
    ├──► Ollama (127.0.0.1:11434)  — query embedding
    │
    └──► Qdrant (127.0.0.1:6333)   — vector search + hybrid re-ranking
```

The MCP server is a standalone Python script. No LlamaIndex, no gtt_bot imports. It talks directly to Ollama and Qdrant over HTTP, runs the same hybrid scoring algorithm as the Discord bot (vector similarity + keyword matching + acronym-to-filename expansion), and returns ranked results to Hermes.

---

## Tools exposed

| Tool | Description |
|---|---|
| `search_gtt_vault` | Hybrid search (vector + keyword) over the vault. Use specific terms — e.g. "engineering mentorship" not "what is mentorship?" |
| `list_gtt_topics` | List all topic names from the indexed vault. Useful for discovering what's available. |

---

## Prerequisites

- GTT Bot Docker stack running (`docker compose up -d`) — Ollama and Qdrant must be reachable on localhost
- Python 3.10+
- Hermes Agent installed ([install guide](https://github.com/NousResearch/hermes-agent#quick-install))

---

## Setup

### 1. Create the MCP server environment

```powershell
cd services/mcp
python -m venv .hermes
.\.hermes\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Linux/macOS:

```bash
cd services/mcp
python3 -m venv .hermes
source .hermes/bin/activate
pip install -r requirements.txt
```

### 2. Smoke test

```powershell
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
python gtt_mcp_server.py
```

You should see:

```
INFO GTT Vault MCP Server starting
INFO   Ollama: http://127.0.0.1:11434
INFO   Qdrant: http://127.0.0.1:6333
INFO   Collection: vault
INFO Backend services reachable — ready
```

It then waits for MCP protocol messages on stdin. Ctrl+C to stop.

If it says "Cannot reach backend services," your Docker stack isn't running.

### 3. Register with Hermes Agent

Add this to your Hermes config (`hermes config edit` or edit the file directly):

**Windows** (`C:\Users\<you>\AppData\Local\hermes\config.yaml`):

```yaml
mcp_servers:
  gtt_vault:
    command: "C:/Users/<you>/Documents/GitHub/gtt-bot/services/mcp/.hermes/Scripts/python.exe"
    args: ["C:/Users/<you>/Documents/GitHub/gtt-bot/services/mcp/gtt_mcp_server.py"]
    env:
      OLLAMA_HOST: "http://127.0.0.1:11434"
```

**Linux/macOS** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  gtt_vault:
    command: "/path/to/gtt-bot/services/mcp/.hermes/bin/python"
    args: ["/path/to/gtt-bot/services/mcp/gtt_mcp_server.py"]
    env:
      OLLAMA_HOST: "http://127.0.0.1:11434"
```

Replace paths with your actual locations. The `OLLAMA_HOST` env override is needed because the system-level `OLLAMA_HOST` from Docker may not include the `http://` prefix.

### 4. Start Hermes and test

```bash
hermes
```

The startup panel should show:

```
MCP Servers
gtt_vault (stdio) — 2 tool(s)
```

Then ask:

```
search the GTT vault for engineering mentorship
```

Hermes will call `search_gtt_vault`, get the ranked chunks, and summarize them.

---

## Troubleshooting

### MCP server shows "failed" at startup

Check the MCP error log:

```powershell
Get-Content C:\Users\<you>\AppData\Local\hermes\logs\mcp-stderr.log
```

Common causes:
- `ModuleNotFoundError: No module named 'httpx'` — deps installed in wrong venv. Run `& "path/to/.hermes/Scripts/python.exe" -m pip install httpx mcp`
- `Cannot reach backend services` — Docker stack not running. Run `docker compose up -d`
- `UnsupportedProtocol` — `OLLAMA_HOST` missing `http://` prefix. Add the `env` block in the Hermes config.

### MCP connected but "0 tool(s) available"

This is normal — Hermes shows MCP tools separately from built-in tools. The "0 tool(s) available" line refers to tool changes after reload. If the MCP panel shows `gtt_vault — 2 tool(s)`, it's working.

### Force reconnect

Inside Hermes:

```
/reload-mcp
```

---

## Configuration

The MCP server reads these environment variables (all have sensible defaults):

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama embedding endpoint |
| `QDRANT_HOST` | `http://127.0.0.1:6333` | Qdrant vector DB endpoint |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama model for query embedding |
| `QDRANT_COLLECTION` | `vault` | Qdrant collection name (matches indexer) |
| `TOP_K` | `5` | Max results per search |
| `MIN_SCORE` | `0.40` | Minimum hybrid score threshold |
| `KEYWORD_WEIGHT` | `0.5` | Weight of keyword score vs vector score |

Override any of these in the Hermes config `env:` block.

---

## How it relates to the Discord bot

The two systems are completely independent:

| | Discord bot | MCP server |
|---|---|---|
| **Runs in** | Docker container | Native Python venv |
| **Triggered by** | `@GTT Bot` or slash commands | Hermes Agent (any interface) |
| **Answer generation** | Claude via Anthropic API | Hermes (any LLM provider) |
| **Retrieval** | LlamaIndex + Qdrant | Direct HTTP to Ollama + Qdrant |
| **Audience** | GTT community | Personal use |
| **Writes to Qdrant** | No | No |

The indexer is the only process that writes to Qdrant. Both the bot and the MCP server are read-only consumers. Editing a note in Obsidian triggers the indexer, and both consumers see the update on their next query.
