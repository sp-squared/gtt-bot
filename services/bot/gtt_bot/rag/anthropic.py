import logging
import time

import anthropic

from gtt_bot.config import ANTHROPIC_API_KEY, SYSTEM_PROMPT

log = logging.getLogger("bot")

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt (1s, 2s, 4s)


def query_anthropic(question: str, context: str, history: list = None) -> str:
    ac = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "Context from the GTT knowledge base:\n"
        "---------------------\n"
        f"{context}\n"
        "---------------------\n"
        f"Question: {question}\n"
        "Answer: "
    )
    messages = []
    if history:
        for msg in history[:-1]:
            messages.append(msg)
    messages.append({"role": "user", "content": prompt})

    for attempt in range(_MAX_RETRIES + 1):
        try:
            message = ac.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            break
        except anthropic.OverloadedError:
            if attempt == _MAX_RETRIES:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log.warning("Anthropic overloaded (attempt %d/%d), retrying in %.0fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)

    if not message.content:
        return "I'm not able to respond to that."
    return message.content[0].text.strip()