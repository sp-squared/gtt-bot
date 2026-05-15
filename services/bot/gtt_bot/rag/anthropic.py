from anthropic import Anthropic

from gtt_bot.config import ANTHROPIC_API_KEY, ANTHROPIC_TIMEOUT, SYSTEM_PROMPT

_client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=ANTHROPIC_TIMEOUT)


def _enforce_alternation(messages: list) -> list:
    """Ensure messages strictly alternate user/assistant roles.

    The Anthropic API rejects consecutive messages with the same role.
    If two adjacent messages share a role, merge them into one.
    """
    if not messages:
        return messages
    cleaned = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == cleaned[-1]["role"]:
            cleaned[-1] = {
                "role": msg["role"],
                "content": cleaned[-1]["content"] + "\n\n" + msg["content"],
            }
        else:
            cleaned.append(msg)
    return cleaned


def query_anthropic(question: str, context: str, history: list = None) -> str:
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
    messages = _enforce_alternation(messages)

    message = _client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    if not message.content:
        return "I'm not able to respond to that."
    return message.content[0].text.strip()
