from anthropic import Anthropic

from gtt_bot.config import ANTHROPIC_API_KEY, SYSTEM_PROMPT


def query_anthropic(question: str, context: str, history: list = None) -> str:
    ac = Anthropic(api_key=ANTHROPIC_API_KEY)
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

    message = ac.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    if not message.content:
        return "I'm not able to respond to that."
    return message.content[0].text.strip()