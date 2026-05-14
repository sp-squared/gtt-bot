import asyncio
import io
import logging
import re
import time
import zipfile

import discord
from discord import app_commands

import gtt_bot.globals as G
from gtt_bot.config import (
    COOLDOWN_LOCAL,
    DISCORD_MSG_LIMIT,
    MAX_QUESTION_LENGTH,
)
from gtt_bot.discord_utils.cooldown import check_cooldown
from gtt_bot.discord_utils.permissions import is_allowed_guild, is_cooldown_exempt
from gtt_bot.rag.formatters import (
    extractive_summary,
    format_bootstrap_html,
    format_raw_chunks,
    format_raw_chunks_plain,
    split_at_sentence,
)
from gtt_bot.rag.retriever import retrieve_context

log = logging.getLogger("bot")


def setup(tree: app_commands.CommandTree) -> None:
    async def query_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        matches = [
            app_commands.Choice(name=term, value=term)
            for term in G.query_terms
            if current_lower in term.lower()
        ]
        return matches[:25]

    @tree.command(name="knowledge-base", description="Search the GTT vault directly (local, no API cost)")
    @app_commands.describe(
        query="Use specific terms e.g. 'deterministic intent folding' not 'what is DIF'",
        format="Output format: dm (markdown, default) or html (Bootstrap 5 file to DMs)",
    )
    @app_commands.choices(format=[
        app_commands.Choice(name="dm", value="dm"),
        app_commands.Choice(name="html", value="html"),
    ])
    @app_commands.autocomplete(query=query_autocomplete)
    async def knowledge_base(interaction: discord.Interaction, query: str, format: str = "dm"):
        if not is_allowed_guild(interaction.guild_id):
            await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
            return
        if len(query) > MAX_QUESTION_LENGTH:
            await interaction.response.send_message(
                f"Query too long — keep it under {MAX_QUESTION_LENGTH} characters.", ephemeral=True
            )
            return
        if not is_cooldown_exempt(interaction.user):
            remaining = check_cooldown(interaction.user.id, G.local_cooldowns, COOLDOWN_LOCAL)
            if remaining > 0:
                await interaction.response.send_message(
                    f"Slow down — you can search again in {int(remaining) + 1}s.", ephemeral=True
                )
                return
            G.local_cooldowns[interaction.user.id] = time.time()

        await interaction.response.defer(ephemeral=True)

        try:
            nodes = await asyncio.to_thread(retrieve_context, query)
            if not nodes:
                await interaction.followup.send("Nothing found in the knowledge base for that query.", ephemeral=True)
                return

            if format == "html":
                html_content = format_bootstrap_html(query, nodes).encode("utf-8")
                safe_query = re.sub(r'[^\w\s-]', '', query).strip()
                safe_query = re.sub(r'\s+', '-', safe_query)[:60].rstrip('-') or "results"
                filename = f"kb-{safe_query}.html"
                _buf = io.BytesIO()
                with zipfile.ZipFile(_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(filename, html_content)
                zip_bytes = _buf.getvalue()
                try:
                    dm = await interaction.user.create_dm()
                    await dm.send(
                        f"Knowledge base results for **{query}** — {len(nodes)} sources",
                        file=discord.File(io.BytesIO(zip_bytes), filename=f"kb-{safe_query}.zip"),
                    )
                    await interaction.followup.send("Bootstrap HTML sent to your DMs.", ephemeral=True)
                    log.info("knowledge-base HTML sent to %s for query: %s", interaction.user, query)
                except discord.Forbidden:
                    await interaction.followup.send(
                        "Could not DM you — enable DMs from server members.", ephemeral=True
                    )
                return

            summary = extractive_summary(nodes)
            raw = format_raw_chunks(nodes)
            summary_msg = f"**Knowledge Base — Summary**\n\n{summary}"
            raw_msg = f"**Knowledge Base — Raw Chunks**\n\n{raw}"

            try:
                dm = await interaction.user.create_dm()
                raw_plain = format_raw_chunks_plain(nodes)
                summary_msg_dm = f"**Knowledge Base — Summary**\n\n{summary}"
                raw_msg_dm = f"**Knowledge Base — Raw Chunks**\n\n{raw_plain}"
                for chunk in split_at_sentence(summary_msg_dm):
                    await dm.send(chunk)
                for chunk in split_at_sentence(raw_msg_dm):
                    await dm.send(chunk)
                await interaction.followup.send("Results sent to your DMs.", ephemeral=True)
                log.info("knowledge-base results DM'd to %s", interaction.user)
            except discord.Forbidden:
                log.info("DM failed for %s, falling back to ephemeral", interaction.user)
                await interaction.followup.send(summary_msg[:DISCORD_MSG_LIMIT], ephemeral=True)
                for i in range(0, len(raw_msg), DISCORD_MSG_LIMIT):
                    await interaction.followup.send(raw_msg[i: i + DISCORD_MSG_LIMIT], ephemeral=True)
                await interaction.followup.send(
                    "Enable DMs from server members to receive results privately next time.", ephemeral=True
                )

        except Exception:
            log.exception("knowledge-base command failed")
            await interaction.followup.send("Something went wrong with the lookup.", ephemeral=True)

    @tree.command(name="knowledge-search", description="Search the GTT vault in a private thread (visible to mods)")
    @app_commands.describe(query="Use specific terms e.g. 'deterministic intent folding' not 'what is DIF'")
    @app_commands.autocomplete(query=query_autocomplete)
    async def knowledge_search(interaction: discord.Interaction, query: str):
        if not is_allowed_guild(interaction.guild_id):
            await interaction.response.send_message("This bot isn't enabled in this server.", ephemeral=True)
            return
        if len(query) > MAX_QUESTION_LENGTH:
            await interaction.response.send_message(
                f"Query too long — keep it under {MAX_QUESTION_LENGTH} characters.", ephemeral=True
            )
            return
        if not is_cooldown_exempt(interaction.user):
            remaining = check_cooldown(interaction.user.id, G.local_cooldowns, COOLDOWN_LOCAL)
            if remaining > 0:
                await interaction.response.send_message(
                    f"Slow down — you can search again in {int(remaining) + 1}s.", ephemeral=True
                )
                return
            G.local_cooldowns[interaction.user.id] = time.time()

        await interaction.response.defer(ephemeral=True)

        try:
            nodes = await asyncio.to_thread(retrieve_context, query)
            if not nodes:
                await interaction.followup.send("Nothing found in the knowledge base for that query.", ephemeral=True)
                return

            summary = extractive_summary(nodes)
            raw_plain = format_raw_chunks_plain(nodes)
            summary_msg = f"**Knowledge Base — Summary**\n\n{summary}"
            raw_msg = f"**Knowledge Base — Raw Chunks**\n\n{raw_plain}"

            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("Private threads only work in text channels.", ephemeral=True)
                return

            thread_name = f"{interaction.user.display_name}: {query[:50]}"
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            await thread.add_user(interaction.user)

            for chunk in split_at_sentence(summary_msg):
                await thread.send(chunk)
            for chunk in split_at_sentence(raw_msg):
                await thread.send(chunk)

            await interaction.followup.send(
                f"Your results are in a private thread: {thread.mention}", ephemeral=True
            )
            log.info("knowledge-search private thread created for %s", interaction.user)

        except discord.Forbidden as e:
            log.warning(
                "knowledge-search: private thread creation forbidden for %s: %s",
                interaction.user,
                e,
            )
            # Fall back to DMs when the bot lacks CREATE_PRIVATE_THREADS / MANAGE_THREADS.
            try:
                dm = await interaction.user.create_dm()
                for chunk in split_at_sentence(summary_msg):
                    await dm.send(chunk)
                for chunk in split_at_sentence(raw_msg):
                    await dm.send(chunk)
                await interaction.followup.send(
                    "Couldn't create a private thread (bot missing permissions) — results sent to your DMs instead.",
                    ephemeral=True,
                )
                log.info("knowledge-search: fell back to DM for %s", interaction.user)
            except discord.Forbidden:
                await interaction.followup.send(
                    "Could not create a private thread or DM you. Enable DMs from server members and ask an admin to grant the bot `Create Private Threads` + `Manage Threads` permissions.",
                    ephemeral=True,
                )
        except Exception:
            log.exception("knowledge-search command failed")
            await interaction.followup.send("Something went wrong with the search.", ephemeral=True)
