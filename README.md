# RAG + SLM Discord Bot — Architecture Plan

**Goal:** Local, containerized Discord bot that answers questions based on an Obsidian vault using RAG + a small language model.

---

## High-Level Architecture

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
║   │  Indexer service │      │  Discord bot app │      │  Ollama          │       ║
║   │  - Watches vault │◄────►│  - discord.py    │◄────►│  - Qwen 2.5 7B   │       ║
║   │  - Chunks + embeds      │  - LlamaIndex    │      │  - nomic-embed   │       ║
║   └────────┬─────────┘      └────────┬─────────┘      └──────────────────┘       ║
║            │                         │                                           ║
║            ▼                         ▼                                           ║
║         ┌──────────────────────────────┐    ┌──────────────────────────────┐     ║
║         │  Qdrant (vector DB)          │    │  Shared volumes              │     ║
║         │  - Persistent volume         │    │  - vault mount (ro)          │     ║
║         └──────────────────────────────┘    │  - model cache, qdrant data  │     ║
║                                             └──────────────────────────────┘     ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

---

## Data Flow

### Indexing (one-time + on file changes)
1. Indexer watches `/vault` mount
2. Chunks markdown (respecting headers, wikilinks)
3. Calls Ollama → embeddings
4. Stores vectors + metadata in Qdrant

### Query (per Discord message)
1. User mentions bot in Discord
2. Bot receives event via Discord gateway
3. Bot embeds question (Ollama)
4. Bot retrieves top-k chunks (Qdrant)
5. Bot builds prompt + context, calls Ollama SLM
6. Bot posts answer back to Discord

---

## Tech Stack

| Layer | Tech | Purpose |
|---|---|---|
| **SLM runtime** | Ollama | Serves Qwen 2.5 7B + nomic-embed-text |
| **LLM model** | Qwen 2.5 7B Instruct | Answer generation |
| **Embedding model** | nomic-embed-text | Markdown-friendly vectors |
| **Vector DB** | Qdrant | Persistent vector store |
| **Orchestration** | LlamaIndex | RAG pipeline, chunking, retrieval |
| **Discord client** | discord.py | Official bot integration |
| **File watcher** | watchdog (Python) | Auto-reindex on vault change |
| **Language** | Python 3.11+ | Indexer + bot |
| **Containerization** | Docker Compose | Multi-service orchestration |
| **GPU passthrough** | NVIDIA Container Toolkit | If GPU available |

---

## Container Layout

### 4 services in `docker-compose.yml`

1. **`ollama`** — official `ollama/ollama` image, GPU-enabled, exposes port 11434
2. **`qdrant`** — official `qdrant/qdrant` image, exposes port 6333, persistent volume
3. **`indexer`** — custom Python image, mounts vault read-only, runs file watcher
4. **`bot`** — custom Python image, holds Discord token via env var

### Volumes
- `./vault` → `/vault` (read-only, both indexer and bot)
- `ollama_data` → model cache
- `qdrant_data` → vector store persistence

### Network
- Single internal Docker network
- Only `bot` needs outbound to Discord
- Nothing inbound from outside

---

## Hardware Requirements

- **GPU:** 8–12 GB VRAM (NVIDIA recommended for Ollama GPU support)
- **RAM:** 16 GB minimum
- **Disk:** ~10 GB for models + vault size

---

## Discord Setup Notes

- Use **official Discord Bot account** (not self-bot with username/password)
- Self-bots violate Discord ToS and risk account ban
- Bot uses a token from the Discord Developer Portal
- Invite bot to your server with `MESSAGE_CONTENT` and `GUILD_MESSAGES` intents

---

## Local Testing

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- ~10 GB free disk for models
- A Discord bot token ([Developer Portal](https://discord.com/developers/applications) → New Application → Bot → Reset Token)
  - Enable **Privileged Gateway Intents**: `MESSAGE CONTENT INTENT`
  - Invite to your test server via OAuth2 URL Generator with scopes `bot`, permissions `Send Messages` + `Read Message History`
- A folder with some markdown files to act as your vault (a small test vault is fine)

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
```
DISCORD_TOKEN=your_bot_token_here
VAULT_PATH=/absolute/path/to/your/test-vault
```

### 2. Start the stack

```bash
docker compose up -d --build
docker compose logs -f
```

First run takes a few minutes (image builds + downloads).

### 3. Pull models into Ollama (one-time)

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull nomic-embed-text
```

### 4. Verify services

```bash
# Ollama responding
curl http://localhost:11434/api/tags

# Qdrant responding
curl http://localhost:6333/collections

# Indexer chunked + uploaded the vault
docker compose logs indexer | tail -20

# Bot connected to Discord gateway
docker compose logs bot | tail -20
# expect: "Logged in as <bot-name>"
```

### 5. Test from Discord

In the channel where the bot is invited, mention it with a question:

```
@your-bot what does my note about X say?
```

The bot should reply with an answer grounded in your vault notes.

### 6. Test indexer reactivity

Add or edit a markdown file in your vault folder. The indexer should pick it up within a few seconds:

```bash
docker compose logs -f indexer
```

Then ask the bot about the new content.

### Troubleshooting

```bash
# Force a full reindex
docker compose restart indexer

# Wipe the vector store and reindex from scratch
docker compose down
docker volume rm aya_qdrant_data
docker compose up -d

# Rebuild after editing service code
docker compose up -d --build bot
docker compose up -d --build indexer
```

If the bot doesn't respond to mentions, confirm the **MESSAGE CONTENT INTENT** is enabled in the Developer Portal — without it, `discord.py` receives empty message content.
