# GTT Vault → Hermes Agent (MCP Integration)

Exposes the GTT knowledge base as an MCP tool server so Hermes Agent
can search the Obsidian vault from VS Code, CLI, Telegram, or any
other Hermes interface.

Standalone — talks directly to Ollama and Qdrant over HTTP.
No LlamaIndex dependency, no gtt_bot imports. Works with Python 3.10+.

## Prerequisites

- GTT Bot Docker stack running (`docker compose up -d`)
- Hermes Agent installed
- Python 3.10+

## Setup

```powershell
cd C:\Users\colin\Documents\GitHub\gtt-bot\services\mcp
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Test

```powershell
python gtt_mcp_server.py
# Should print "Backend services reachable — ready" then wait.
# Ctrl+C to exit.
```

## Register with Hermes

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  gtt_vault:
    command: "C:/Users/colin/Documents/GitHub/gtt-bot/services/mcp/.venv/Scripts/python.exe"
    args: ["C:/Users/colin/Documents/GitHub/gtt-bot/services/mcp/gtt_mcp_server.py"]
```

## Tools exposed

| Tool               | Description                                     |
|--------------------|-------------------------------------------------|
| `search_gtt_vault` | Hybrid search (vector + keyword) over the vault |
| `list_gtt_topics`  | List all topic names from the indexed vault      |
