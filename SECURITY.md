# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in GTT Bot, please do **not** open a public GitHub issue.

Instead, report it privately by emailing the maintainer or opening a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability).

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix if you have one

You can expect an acknowledgment within 48 hours and a resolution or update within 7 days depending on severity.

## Known Scope

The main attack surfaces for this project:

- **Discord bot token** — stored in `.env`, never committed. Rotate immediately at [Discord Developer Portal](https://discord.com/developers/applications) if compromised.
- **Anthropic API key** — stored in `.env`. Rotate at [console.anthropic.com](https://console.anthropic.com) if compromised.
- **Guild allowlist** — `ALLOWED_GUILDS` in `.env` controls which servers the bot responds in. Leaving it empty allows any server to use your API key.
- **Vector store** — Qdrant is bound to `127.0.0.1` and not exposed externally. Vault content is accessible to anyone who can query the local Qdrant instance.

## Out of Scope

- Vulnerabilities in third-party dependencies (Qdrant, Ollama, discord.py, LlamaIndex, Anthropic SDK) — report these upstream.
- Issues requiring physical access to the host machine.
