import os
import re

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OLLAMA_HOST = os.environ["OLLAMA_HOST"]
QDRANT_HOST = os.environ["QDRANT_HOST"]
EMBED_MODEL = os.environ["EMBED_MODEL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TOP_K = int(os.environ.get("TOP_K", "5"))
MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.40"))
KEYWORD_WEIGHT = float(os.environ.get("KEYWORD_WEIGHT", "0.5"))

ALLOWED_CHANNELS = set(
    int(x.strip()) for x in os.environ.get("ALLOWED_CHANNELS", "").split(",") if x.strip()
)
ALLOWED_GUILDS = set(
    int(x.strip()) for x in os.environ.get("ALLOWED_GUILDS", "").split(",") if x.strip()
)
REQUIRED_ROLE = os.environ.get("REQUIRED_ROLE", "").strip()
COOLDOWN_ANTHROPIC = int(os.environ.get("COOLDOWN_SECONDS", "30"))
COOLDOWN_LOCAL = int(os.environ.get("COOLDOWN_LOCAL_SECONDS", "10"))
COOLDOWN_EXEMPT_USERS = set(
    int(x.strip()) for x in os.environ.get("COOLDOWN_EXEMPT_USERS", "").split(",") if x.strip()
)
COOLDOWN_EXEMPT_ROLES = set(
    x.strip() for x in os.environ.get("COOLDOWN_EXEMPT_ROLES", os.environ.get("COOLDOWN_EXEMPT_ROLE", "")).split(",") if x.strip()
)
MAX_QUESTION_LENGTH = int(os.environ.get("MAX_QUESTION_LENGTH", "500"))
THREAD_HISTORY_LIMIT = int(os.environ.get("THREAD_HISTORY_LIMIT", "30"))
ANTHROPIC_TIMEOUT = float(os.environ.get("ANTHROPIC_TIMEOUT", "30"))
COOLDOWN_PRUNE_INTERVAL = int(os.environ.get("COOLDOWN_PRUNE_INTERVAL", "300"))

MOD_CHANNEL_ID = int(os.environ.get("MOD_CHANNEL_ID", "0"))
GENERAL_CHANNEL_ID = int(os.environ.get("GENERAL_CHANNEL_ID", "0"))
NEW_ACCOUNT_DAYS = int(os.environ.get("NEW_ACCOUNT_DAYS", "7"))
SUSPICIOUS_MSG_LENGTH = int(os.environ.get("SUSPICIOUS_MSG_LENGTH", "200"))
REQUIRED_ROLE_FOR_AUTOMOD = os.environ.get("REQUIRED_ROLE", "GTT Sub Level 0").strip()
TIMEOUT_LEAVE_WINDOW = int(os.environ.get("TIMEOUT_LEAVE_WINDOW", "600"))

DEFAULT_USE_THREADS = os.environ.get("USE_THREADS", "true").lower() == "true"

DISCORD_MSG_LIMIT = 2000

SELF_PROMO_THRESHOLD = int(os.environ.get("SELF_PROMO_THRESHOLD", "2"))

_raw_patterns = os.environ.get("SELF_PROMO_PATTERNS", "")
if _raw_patterns:
    SELF_PROMO_PATTERNS = [
        (t.strip(), re.compile(f"\\b{re.escape(t.strip())}\\b", re.IGNORECASE))
        for t in _raw_patterns.split(",") if t.strip()
    ]
else:
    SELF_PROMO_PATTERNS = []

SYSTEM_PROMPT = """You are the GTT Bot, the AI assistant for Goju Tech Talk (GTT). You run on claude-sonnet-4-5-20250929 (Claude Sonnet 4.5) via the Anthropic API. When asked what model you are, say Claude Sonnet 4.5. Do not say Claude 3.5 Sonnet — that is a different model. — a community built around honest tech analysis, deep critical thinking, and the truth about AI, software engineering, and the future of programming. GTT brings together software engineers, scientists, technology enthusiasts, and curious minds who value intellectual honesty over hype.

You were built by the GTT community using a knowledge graph of atomic notes representing Goju's actual positions.

You are NOT a generic helpful assistant. You are a technically grounded, intellectually honest voice shaped by a specific worldview. Act like it.

## Core Worldview

You reason from these core positions:

1. AI Hype vs Reality — AI hype is structural, not accidental. It serves financial interests. LLMs are pattern-matching engines: genuinely useful in narrow ways, dangerously overstated in broad claims. Be accurate about AI, not anti-AI.

2. Deterministic Intent Folding (DIF) — DIF is Merly's own ML technology: deterministic, up to 1,000,000x faster than LLMs for specific tasks, and runs entirely locally. It is NOT a generic principle — it is a specific architecture that enables Repository Lifetime Reasoning (RLR), which is how Mentor detects vibe coded projects at scale. All major AI systems (Google, Meta, Microsoft, Apple) are stochastic and cannot replicate this.

3. Vibe Coding is Not Engineering — Using AI coding tools is fine. Shipping code you don't understand is abdication. DIF + RLR is the technical mechanism for detecting vibe coding by analyzing the full evolution of a repository, not just a snapshot.

4. Critical Thinking as Engineering Discipline — Critical thinking is a technical competency. Separate claim from evidence. Ask who benefits. Distinguish demo from production. Prefer falsification. Hold uncertainty explicitly.

5. Data-Oriented Design — Performance problems are usually data layout problems. Understanding how data moves through memory is a core engineering skill.

6. Tech Industry Analysis — Every company has an incentive structure. Understand it. No boosters, no reflexive cynics.

## Tone and Behavior

- Be direct. State your actual position.
- Be honest about uncertainty.
- Challenge lazy questions and surface hidden assumptions — but do so with curiosity, not contempt.
- Do not validate hype uncritically.
- Do not be contrarian for sport — the goal is accuracy.
- When DIF comes up, be precise: it is Merly's specific technology, not a generic design pattern.
- GTT is a sanctuary for people at all levels of technical knowledge. A new member asking a basic question deserves a real answer, not a lecture. Raise the quality of thinking in the room — don't gatekeep who belongs in it.
- Be rigorous and kind — both at once. Push back on vague questions by asking for clarity, not by making the person feel unwelcome.

## CRITICAL FORMATTING RULES — NEVER VIOLATE

- NEVER use numbered lists or bullet points.
- NEVER open with "To better understand", "To effectively", "Great question", "Certainly", or "Of course".
- ALWAYS respond in plain prose paragraphs only.
- NEVER end with "Would you like me to elaborate?" or similar.
- NEVER close with "By following these steps" or similar.

## Response Format

- Shorter is better. GTT people read.
- Lead with the honest take. Nuance after.
- Reference the knowledge base when relevant.
- No fluff. No "great question!", no "certainly!", no "as an AI language model..."
- Ask one clarifying question if genuinely ambiguous.

## When Answering Without Vault Context

This prompt either contains a "Context from the GTT knowledge base" block or it does not. When no context block is present, you are drawing from training knowledge rather than the vault.

If the question touches GTT-specific concepts — DIF, RLR, Mentor, Merly, vibe coding, ownership deficit, blast radius, data-oriented design, or repository lifetime reasoning — answer accurately from training, then close with exactly one line:

"For the authoritative GTT position, try `/knowledge-search <relevant term>`."

Replace <relevant term> with the most specific term from the question (e.g. `deterministic intent folding`, `repository lifetime reasoning`, `vibe coding detection`). Do not add this nudge for general questions, off-topic questions, or questions that are clearly not about GTT-specific concepts."""

GTT_QUERY_TERMS = [
    "deterministic intent folding",
    "DIF architecture",
    "DIF vs LLM",
    "DIF verifier stochastic AI",
    "repository lifetime reasoning",
    "RLR vibe coding detection",
    "vibe coding is not engineering",
    "vibe coding commit history",
    "ownership deficit technical debt",
    "code review ownership verification",
    "commit history as signal",
    "blast radius production systems",
    "AI hype structural incentives",
    "LLM pattern matching limitations",
    "critical thinking engineering discipline",
    "falsification over confirmation",
    "data oriented design",
    "structure of arrays cache coherency",
    "systems programming memory layout",
    "tech industry analysis incentives",
    "open source as strategy",
    "Mentor Merly vibe coding detection",
    "complexity distribution abstraction cost",
    "test coverage intent ownership",
    "knowledge graph vs database",
    "engineering mentorship craft",
    "GTT community rules",
    "gtt bot architecture stack",
]

GTT_GLOSSARY = [
    {
        "term": "DIF",
        "full": "Deterministic Intent Folding",
        "definition": (
            "Merly's proprietary ML architecture. Deterministic — same input always produces "
            "same output, unlike stochastic LLMs. Up to 1,000,000x faster than LLMs for specific "
            "tasks. Runs entirely locally with no cloud dependency. Not a generic design principle — "
            "a specific technology Merly built."
        ),
        "example": "/knowledge-search deterministic intent folding merly architecture",
    },
    {
        "term": "RLR",
        "full": "Repository Lifetime Reasoning",
        "definition": (
            "Analyzing the full evolution of a software repository — every commit, every "
            "structural change over time — rather than just its current snapshot. Enabled by "
            "DIF's constant-time inference. How Mentor detects vibe coded projects at scale."
        ),
        "example": "/knowledge-search repository lifetime reasoning vibe coding detection",
    },
    {
        "term": "Vibe Coding",
        "full": "Vibe Coding",
        "definition": (
            "Using AI tools to generate code you don't understand and shipping it anyway. "
            "Using AI tools is fine. Shipping code you cannot explain, debug, or defend is "
            "abdication of engineering. The distinction is ownership, not tooling."
        ),
        "example": "/knowledge-search vibe coding ownership debugging commit history",
    },
    {
        "term": "Mentor",
        "full": "Mentor by Merly",
        "definition": (
            "Merly's first DIF-powered product. Analyzes software repositories for signs of "
            "vibe coding by examining commit history at scale. Runs entirely locally. "
            "Contributes results to a global database for quarantining compromised open source projects."
        ),
        "example": "@GTT Bot how does Mentor use RLR to detect vibe coding?",
    },
    {
        "term": "DOD",
        "full": "Data-Oriented Design",
        "definition": (
            "Organizing data for how it flows through hardware, not how it maps to concepts. "
            "Structure of Arrays over Array of Structures. Cache lines stay hot, prefetcher works, "
            "branch prediction succeeds. Foundational to DIF's performance — constant-time inference "
            "requires control over memory layout."
        ),
        "example": "/knowledge-search data oriented design",
    },
    {
        "term": "Ownership Deficit",
        "full": "Ownership Deficit",
        "definition": (
            "Technical debt is not bad code — it's code nobody can confidently own, debug, or "
            "explain. Debt is an ownership problem, not just a quality problem. A codebase where "
            "nobody can answer 'why does this work?' is in debt regardless of test coverage or formatting."
        ),
        "example": "/knowledge-search technical debt ownership deficit commit history",
    },
    {
        "term": "Blast Radius",
        "full": "Blast Radius",
        "definition": (
            "The scope of damage when a production system fails. In GTT: the compounding cost "
            "of shipping code nobody understands — silent breakage, undebuggable failures, "
            "security holes from AI-generated logic, skill atrophy, and valuation fraud in "
            "acquired codebases."
        ),
        "example": "/knowledge-search blast radius production systems complexity debt",
    },
    {
        "term": "Code Review as Ownership Verification",
        "full": "Code Review as Ownership Verification",
        "definition": (
            "Code review is not just 'does it work?' — it's verifying that the author "
            "understands what they built. The real signal: can they explain why, what breaks "
            "if you change this line, what alternatives were rejected. 'Tests pass' is the "
            "baseline. The explanation is the standard."
        ),
        "example": "/knowledge-search code review ownership verification PR rationale",
    },
    {
        "term": "AI Hype",
        "full": "AI Hype vs Reality",
        "definition": (
            "AI hype is structural, not accidental — it serves financial interests. LLMs are "
            "pattern-matching engines: genuinely useful in narrow ways, dangerously overstated "
            "in broad claims. The GTT position is accuracy: neither boosterism nor reflexive "
            "skepticism. Ask who benefits from you believing the marketing."
        ),
        "example": "/knowledge-search ai hype vs reality",
    },
    {
        "term": "Critical Thinking",
        "full": "Critical Thinking as Engineering Discipline",
        "definition": (
            "Separating claim from evidence. Asking who benefits. Distinguishing demo from "
            "production. Preferring falsification over confirmation. Holding uncertainty explicitly. "
            "A technical competency, not a soft skill — applied to tools, architectures, and "
            "vendor claims with the same rigor as code."
        ),
        "example": "/knowledge-search critical thinking engineering discipline",
    },
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
URL_RE = re.compile(r"https?://\S+")
CHANNEL_MENTION_RE = re.compile(r"<#\d+>")
CLEAN_URL_RE = re.compile(r"https?://[^\s]+")
