import logging

import discord
from discord import app_commands

from gtt_bot.config import GTT_GLOSSARY

log = logging.getLogger("bot")

_TERM_CHOICES = [
    app_commands.Choice(name=f"{e['term']} — {e['full']}" if e['term'] != e['full'] else e['term'], value=e['term'])
    for e in GTT_GLOSSARY
]


def _format_entry(entry: dict) -> str:
    header = f"**{entry['term']}** — {entry['full']}" if entry['term'] != entry['full'] else f"**{entry['term']}**"
    return f"{header}\n{entry['definition']}\n*Try: `{entry['example']}`*"


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="glossary", description="GTT terminology — definitions and example queries")
    @app_commands.describe(term="Look up a specific term, or leave blank for the full glossary")
    @app_commands.choices(term=_TERM_CHOICES)
    async def glossary(interaction: discord.Interaction, term: str = None):
        if term:
            entry = next((e for e in GTT_GLOSSARY if e['term'] == term), None)
            if not entry:
                await interaction.response.send_message(f"Term `{term}` not found.", ephemeral=True)
                return
            await interaction.response.send_message(_format_entry(entry), ephemeral=True)
            return

        # Full glossary — send all entries
        lines = ["**GTT Glossary**\n"]
        for entry in GTT_GLOSSARY:
            lines.append(_format_entry(entry))

        full = "\n\n".join(lines)

        # Split across messages if needed
        chunks = []
        current = ""
        for block in lines:
            candidate = (current + "\n\n" + block).strip()
            if len(candidate) > 1950:
                if current:
                    chunks.append(current.strip())
                current = block
            else:
                current = candidate
        if current:
            chunks.append(current.strip())

        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

        log.info("glossary displayed for %s (term=%s)", interaction.user, term)
