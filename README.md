# GTT Bot

A local, containerized Discord bot for the [Goju Tech Talk (GTT)](https://youtube.com/@gojutechtalk) community. Answers questions grounded in an Obsidian knowledge base using RAG — local vector search for retrieval, Claude (Anthropic API) for opinionated, GTT-voiced responses.

---

#### mtg_database Database Schema

![screenshot](/img/gtt_bot_architecture.svg)

## Architecture

```
┌─────────────────────┐                          ┌─────────────────────┐
│  Obsidian vault     │                          │  Discord            │
│  (markdown files)   │                          │  (bot account)      │
└──────────┬──────────┘                          └──────────┬──────────┘
           │ mounted (ro)                                   │ gateway
           ▼                                                ▼
╔══════════════════════════ Docker host (docker-compose) ══════════════════════════╗
║                                                                                  ║
║   ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐       ║
║   │  Indexer service │      │  Discord bot     │      │  Ollama          │       ║
║   │  - Watches vault │◄────►│  - discord.py    │◄────►│  - nomic-embed   │       ║
║   │  - Chunks + embeds      │  - LlamaIndex    │      └──────────────────┘       ║
║   └────────┬─────────┘      └────────┬─────────┘                                ║
║            │                         │ Anthropic API (answer generation)         ║
║            ▼                         ▼                                           ║
║         ┌──────────────────────────────┐                                         ║
║         │  Qdrant (vector DB)          │                                         ║
║         │  - Persistent volume         │                                         ║
║         └──────────────────────────────┘                                         ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

### Data flow

**Indexing** (on startup + on vault file changes)
1. Indexer watches the `/vault` mount
2. Chunks markdown files respecting headers and wikilinks
3. Calls Ollama → `nomic-embed-text` embeddings
4. Stores vectors + metadata in Qdrant

**Query** (per Discord mention)
1. User mentions `@GTT Bot` in Discord
2. Bot embeds the question (Ollama, local)
3. Bot retrieves top-k chunks (Qdrant, local)
4. Bot sends context + question to Claude via Anthropic API
5. Bot posts answer back to Discord with source citations

**`/knowledge-base` query** (fully local, no API cost)
1. User runs `/knowledge-base <query>`
2. Bot embeds query and retrieves matching chunks (Ollama + Qdrant)
3. Returns summary and raw chunks directly — no LLM involved

---

## Bot commands

| Command | Description | Cost |
|---|---|---|
| `@GTT Bot <question>` | Ask a question, get a GTT-voiced answer | Anthropic API |
| `/knowledge-base <query>` | Search the vault directly, returns raw chunks | Free (local) |
| `/thread-mode on/off` | Toggle thread replies on or off | Free (local) |
| `/status` | Show knowledge base size, uptime, config | Free (local) |

---

## Tech stack

| Layer | Tech | Purpose |
|---|---|---|
| **Answer generation** | Claude (Anthropic API) | GTT-voiced responses |
| **Embedding model** | nomic-embed-text (Ollama) | Vault chunk embeddings |
| **Vector DB** | Qdrant | Persistent vector store |
| **RAG pipeline** | LlamaIndex | Chunking, retrieval |
| **Discord client** | discord.py | Bot integration |
| **File watcher** | watchdog | Auto-reindex on vault change |
| **Containerization** | Docker Compose | Multi-service orchestration |

---

## Hardware requirements

- **RAM:** 16 GB minimum (32 GB recommended)
- **Disk:** ~5 GB for embedding model + vault index
- **GPU:** Optional — only used for Ollama embeddings

---

## Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- A Discord bot token — [Developer Portal](https://discord.com/developers/applications) → New Application → Bot → Reset Token
  - Enable **Privileged Gateway Intents**: `MESSAGE CONTENT INTENT`
  - Invite to your server via OAuth2 URL Generator with scopes `bot` and `applications.commands`, permissions `Send Messages` + `Read Message History` + `Create Public Threads`
- An Anthropic API key — [console.anthropic.com](https://console.anthropic.com) → API Keys
- An Obsidian vault (or any folder of markdown files)

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```
DISCORD_TOKEN=your_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_key_here
VAULT_PATH=/absolute/path/to/your/vault

# Lock the bot to specific servers (recommended)
ALLOWED_GUILDS=your_guild_id_here
```

To get your guild ID: enable Developer Mode in Discord (Settings → Advanced), then right-click your server name → Copy Server ID.

### 2. Start the stack

```bash
docker compose up -d --build
```

First run downloads images and builds containers. Takes a few minutes.

### 3. Pull the embedding model (one-time)

```bash
docker compose exec gtt-ollama ollama pull nomic-embed-text
```

Then restart the indexer so it can build the vault index:

```bash
docker compose restart gtt-indexer
```

### 4. Verify

```bash
# Bot connected
docker compose logs gtt-bot --tail=20
# expect: "Slash commands synced" and "Logged in as <bot-name>"

# Indexer built the vault
docker compose logs gtt-indexer --tail=20
# expect: "Index build complete"
```

### 5. Test from Discord

```
@GTT Bot what is DIF?
```

```
/knowledge-base repository lifetime reasoning
```

```
/status
```

---

## Configuration reference

All settings go in `.env`. See `.env.example` for the full list with descriptions.

| Variable | Default | Description |
|---|---|---|
| `DISCORD_TOKEN` | required | Bot token from Discord Developer Portal |
| `ANTHROPIC_API_KEY` | required | API key from console.anthropic.com |
| `VAULT_PATH` | required | Absolute path to your Obsidian vault |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `QDRANT_COLLECTION` | `vault` | Qdrant collection name |
| `TOP_K` | `5` | Number of vault chunks retrieved per query |
| `ALLOWED_GUILDS` | *(all)* | Comma-separated guild IDs. Empty = allow all |
| `ALLOWED_CHANNELS` | *(all)* | Comma-separated channel IDs. Empty = allow all |
| `COOLDOWN_SECONDS` | `30` | Per-user cooldown for `@mention` (Anthropic API) |
| `COOLDOWN_LOCAL_SECONDS` | `10` | Per-user cooldown for `/knowledge-base` |
| `MAX_QUESTION_LENGTH` | `500` | Max characters per question |
| `USE_THREADS` | `false` | Reply in threads instead of inline |

### Thread mode

Set `USE_THREADS=true` in `.env` to default thread mode on for all guilds. Any member in an allowed server can also toggle it at runtime with `/thread-mode on` or `/thread-mode off` — this overrides the `.env` default for that server until the bot restarts.

---

## Knowledge base

The bot's knowledge base is an Obsidian vault of atomic notes. The indexer watches the vault folder and automatically reindexes when files change.

Notes follow a Zettelkasten structure with wikilinks (`[[note-title]]`) for connections. The bot retrieves the most relevant chunks for each question and uses them as context for the answer.

To update the knowledge base: add or edit markdown files in your vault folder. The indexer picks up changes within a few seconds. To force a full reindex:

```bash
docker compose restart gtt-indexer
```

---

## Security

- **`ALLOWED_GUILDS`** — strongly recommended. Without it, anyone who discovers your bot's Client ID can invite it to their server and use your Anthropic API key.
- **`.env`** — never commit this file. It's in `.gitignore` by default.
- **Ports** — Qdrant (6333) and Ollama (11434) are bound to `127.0.0.1` and not accessible from outside the host.
- **Rate limiting** — per-user cooldowns on both paths. Adjust `COOLDOWN_SECONDS` and `MAX_QUESTION_LENGTH` to control API cost exposure.

---

## Troubleshooting

```bash
# Check bot logs
docker compose logs gtt-bot --tail=30

# Check indexer logs
docker compose logs gtt-indexer --tail=30

# Force reindex
docker compose restart gtt-indexer

# Rebuild after editing bot code
docker compose up --build gtt-bot -d

# Wipe vector store and reindex from scratch
docker compose down
docker volume rm gtt-bot_qdrant_data
docker compose up -d --build

# Pull a different embedding model
docker compose exec gtt-ollama ollama pull <model-name>
```

If the bot doesn't respond to mentions, confirm **MESSAGE CONTENT INTENT** is enabled in the Developer Portal — without it, discord.py receives empty message content.

If `/knowledge-base` returns nothing, the indexer may not have run yet. Check its logs and restart if needed.

---

## Contributing

This is a proof-of-concept built for the GTT community. The knowledge base (vault) is separate from the bot code by design — the code is public, the knowledge base is yours to keep private or share as you choose.

To adapt this for your own community: replace the `SYSTEM_PROMPT` in `services/bot/main.py` with your own worldview, drop your markdown notes into the vault, and you have a bot that reflects your community's actual knowledge and voice.
