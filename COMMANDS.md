# GTT Bot — Slash Command Reference

A complete reference for all GTT Bot slash commands.

---

## Knowledge Commands

### `@GTT Bot <question>`
Ask a question and get a GTT-voiced answer grounded in the knowledge base.

- Requires `GTT Sub Level 0` role
- 30 second cooldown per user (exempt users bypass this via `COOLDOWN_EXEMPT_USERS`)
- Max 500 characters
- Replies in a public thread by default (toggle with `/thread-mode`)
- Supports follow-up questions inside the thread (remembers last 30 bot-related exchanges)

**Examples:**
```
@GTT Bot what is DIF?
@GTT Bot how does vibe coding relate to technical debt?
@GTT Bot based on what you just said, how does Google approach this differently?
```

---

### `/knowledge-base <query>`
Search the GTT vault directly. Results sent to your DMs only — mods cannot see.

- Free (no API cost, runs locally)
- 10 second cooldown per user
- Use specific terms, not questions

**Examples:**
```
/knowledge-base deterministic intent folding
/knowledge-base repository lifetime reasoning vibe coding
/knowledge-base blast radius production systems
/knowledge-base cache coherency data layout
```

---

### `/knowledge-search <query>`
Search the GTT vault in a private thread. Only you and mods can see it. Deletable by mods.

- Free (no API cost, runs locally)
- 10 second cooldown per user
- Use specific terms, not questions

**Examples:**
```
/knowledge-search ownership vs generation
/knowledge-search falsification over confirmation
/knowledge-search meta llama open source strategy
```

---

## Server Commands

### `/glossary [term]`
GTT terminology — definitions and example queries for every core concept.

- Available to all members
- Ephemeral — only you see the output
- Leave `term` blank for the full glossary, or pick a specific term from the dropdown

**Terms covered:** DIF, RLR, Vibe Coding, Mentor, DOD, Ownership Deficit, Blast Radius, Code Review as Ownership Verification, AI Hype, Critical Thinking

---

### `/thread-mode <on|off>`
Toggle whether `@GTT Bot` replies in threads or inline.

- Available to all members
- Per-server setting, resets on bot restart
- Ephemeral — only you see the confirmation

**Options:**
```
/thread-mode on    ← bot creates a thread for each @mention (default)
/thread-mode off   ← bot replies inline
```

---

### `/status`
Show GTT Bot status, knowledge base info, and current configuration.

- Available to all members
- Ephemeral — only you see the output

**Shows:** chunks indexed, embed model, LLM, API access role, thread mode, uptime, cooldowns, max question length

---

## Export Commands
*GTT Team and admin only*

### `/export <channel> <format> <limit> <reactions>`
Export a single channel's history as a zip file sent to your DMs.

**Parameters:**
| Parameter | Options | Default | Notes |
|---|---|---|---|
| `channel` | any text channel | required | Channel to export |
| `format` | `text` `json` `html` | required | Output format |
| `limit` | any number | `500` | `0` = unlimited |
| `reactions` | `yes` `no` | `yes` | Slower with yes |

**What's included in the zip:**
- Message export file (`.txt`, `.json`, or `.html`)
- `attachments/` — downloaded images and files
- `channel-urls.txt` — extracted URLs
- `channel-pinned.txt` — pinned messages
- `channel-threads/` — thread content

**Examples:**
```
/export channel:#knowledge-base format:json limit:0 reactions:no
/export channel:#general format:html limit:500 reactions:yes
/export channel:#philosophy format:text limit:1000 reactions:no
```

---

### `/export-all <format> <limit> <reactions>`
Export all server channels to local disk at `gtt-exports/<timestamp>/`.

**Parameters:**
| Parameter | Options | Default | Notes |
|---|---|---|---|
| `format` | `text` `json` `html` | required | Output format |
| `limit` | any number | `500` | `0` = unlimited |
| `reactions` | `yes` `no` | `yes` | Slower with yes |

**What's saved per channel:**
- Message export file
- `channel-attachments/` — downloaded files
- `channel-urls.txt` — extracted URLs
- `channel-pinned.txt` — pinned messages
- `channel-threads/` — thread content

**Also saves:**
- `assets/emoji/` — all custom server emoji
- `assets/members.json` — member snapshot with roles and join dates

**Summary sent to your DMs when complete.**

**Examples:**
```
/export-all format:json limit:0 reactions:no
/export-all format:html limit:500 reactions:yes
/export-all format:text limit:1000 reactions:no
```

---

### `/export-state <format> <reactions>`
Incremental export — only fetches new messages since the last run. Saves to `gtt-exports/latest/`.

**First run:** full bootstrap of all history (slow, same as `/export-all`)
**Every run after:** only new content appended to existing files (fast)

**Parameters:**
| Parameter | Options | Default | Notes |
|---|---|---|---|
| `format` | `all` `text` `json` `html` | `all` | `all` generates all three formats in one pass |
| `reactions` | `yes` `no` | `no` | Recommended: keep `no` for speed |

**Summary sent to your DMs when complete.**

**Examples:**
```
/export-state format:all reactions:no      ← recommended for regular backups
/export-state format:json reactions:no     ← JSON only, fastest
/export-state format:html reactions:yes    ← HTML with reactions, slowest
```

**To reset and re-bootstrap from scratch:**
1. Delete `gtt-exports/export-state.json`
2. Delete `gtt-exports/latest/`
3. Run `/export-state format:all reactions:no`

---

### `/export-thread <format> <reactions>`
Export the current thread you're in. Must be run from inside a thread.

**Parameters:**
| Parameter | Options | Default | Notes |
|---|---|---|---|
| `format` | `text` `json` `html` | required | Output format |
| `reactions` | `yes` `no` | `no` | Include reactions |

**Sent to your DMs as a zip file.**

**Examples:**
```
/export-thread format:text reactions:no     ← plain transcript
/export-thread format:json reactions:no     ← structured data
/export-thread format:html reactions:no     ← browsable offline
```

---

## Format Comparison

| Format | Best for | Includes reactions | Machine readable |
|---|---|---|---|
| `text` | Quick reading, Obsidian import | Inline as emoji(count) | No |
| `json` | Processing, future imports, Matrix | Full user lists | Yes |
| `html` | Browsing offline in browser | Colored badges | No |
| `all` | Complete backup (export-state only) | Depends on reactions setting | Yes |

---

## Tips

**For better knowledge base results:** use specific terminology rather than questions.
- ❌ `what is DIF`
- ✅ `deterministic intent folding merly architecture`

**For exports:** use `reactions:no` for speed on large channels. Add reactions later in incremental runs when fewer messages need processing.

**For backups:** run `/export-state format:all reactions:no` regularly. It's fast after the initial bootstrap and keeps `latest/` current.
