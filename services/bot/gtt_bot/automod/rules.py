import logging
from datetime import timedelta

import discord

from gtt_bot.config import (
    GENERAL_CHANNEL_ID,
    SELF_PROMO_PATTERNS,
    SUSPICIOUS_MSG_LENGTH,
    NEW_ACCOUNT_DAYS,
    REQUIRED_ROLE_FOR_AUTOMOD,
)
from gtt_bot.discord_utils.permissions import can_be_timed_out
from gtt_bot.automod.alerts import send_mod_alert

log = logging.getLogger("bot")


async def check_automod(message: discord.Message):
    """Check message for automod rules and take action if triggered."""
    if not message.guild:
        return
    member = message.author
    if not isinstance(member, discord.Member):
        return

    # Skip automod entirely for members with roles above GTT Bot in the hierarchy
    if not can_be_timed_out(member):
        return

    content = message.content
    rule = None
    timeout_duration = None

    # Rule 1: @everyone or @here attempt — any channel, 1 minute timeout
    if "@everyone" in content or "@here" in content:
        rule = "`@everyone` / `@here` attempt"
        timeout_duration = timedelta(minutes=1)

    # Rule 2: Self-promo in #general — indefinite timeout (28 days)
    elif (
        message.channel.id == GENERAL_CHANNEL_ID
        and SELF_PROMO_PATTERNS
        and SELF_PROMO_PATTERNS.search(content)
    ):
        rule = "Self-promotion in `#general`"
        timeout_duration = timedelta(days=28)

    # Rule 3: New account + no role + long message in #general → flag only, no timeout
    if not rule and message.channel.id == GENERAL_CHANNEL_ID and len(content) > SUSPICIOUS_MSG_LENGTH:
        account_age = (discord.utils.utcnow() - member.created_at).days
        has_role = any(r.name == REQUIRED_ROLE_FOR_AUTOMOD for r in member.roles)
        if account_age < NEW_ACCOUNT_DAYS and not has_role:
            await send_mod_alert(
                message.guild,
                member,
                f"New account ({account_age}d old), no `{REQUIRED_ROLE_FOR_AUTOMOD}` role, long message in `#general`",
                content,
                timed_out=False,
                timeout_duration=None,
                flag_only=True,
            )
        return

    if not rule:
        return

    timed_out = False
    if can_be_timed_out(member) and timeout_duration:
        try:
            await member.timeout(timeout_duration, reason=f"Automod: {rule}")
            timed_out = True
            log.info("Timed out %s for rule: %s", member, rule)
        except discord.Forbidden:
            log.warning("Could not time out %s — missing permissions", member)
        except Exception:
            log.exception("Timeout failed for %s", member)

    await send_mod_alert(message.guild, member, rule, content, timed_out, timeout_duration=timeout_duration)
