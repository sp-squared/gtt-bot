import logging

import discord

from gtt_bot.config import MOD_CHANNEL_ID

log = logging.getLogger("bot")


async def send_mod_alert(
    guild: discord.Guild,
    member: discord.Member,
    rule: str,
    message_content: str,
    timed_out: bool,
    timeout_duration=None,
    flag_only: bool = False,
    timeout_fail_reason: str | None = None,
):
    """Post an alert to the mod channel."""
    if not MOD_CHANNEL_ID:
        return
    mod_channel = guild.get_channel(MOD_CHANNEL_ID)
    if not mod_channel:
        return

    account_age = (discord.utils.utcnow() - member.created_at).days
    minutes = int(timeout_duration.total_seconds() // 60) if timeout_duration else 0
    if minutes >= 60 * 24:
        duration_str = f"{minutes // (60 * 24)} day(s)"
    else:
        duration_str = f"{minutes} min"

    if flag_only:
        timeout_status = "👀 No action taken — flagged for mod review"
    elif timed_out:
        timeout_status = f"✅ Timed out ({duration_str})"
    elif timeout_fail_reason == "missing permission":
        timeout_status = "⚠️ Could not time out (bot missing Moderate Members permission)"
    elif timeout_fail_reason == "error":
        timeout_status = "⚠️ Could not time out (unexpected error — check logs)"
    else:
        timeout_status = "⚠️ Could not time out (role too high)"

    alert = (
        f"🚨 **Automod Alert**\n\n"
        f"**User:** {member.mention} (`{member}` · ID: `{member.id}`)\n"
        f"**Account age:** {account_age} days\n"
        f"**Rule triggered:** {rule}\n"
        f"**Action:** {timeout_status}\n"
        f"**Message:**\n> {message_content[:500]}\n\n"
        f"Mods: review and take action if needed."
    )
    await mod_channel.send(alert)
    log.info("Automod alert sent for %s — rule: %s", member, rule)


async def send_timeout_leave_alert(guild: discord.Guild, member: discord.Member, elapsed_seconds: float, rule: str):
    """Alert mods when a timed-out member leaves the server shortly after."""
    if not MOD_CHANNEL_ID:
        return
    mod_channel = guild.get_channel(MOD_CHANNEL_ID)
    if not mod_channel:
        return

    minutes, seconds = divmod(int(elapsed_seconds), 60)
    elapsed_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

    alert = (
        f"🚪 **Timed-out member left server**\n\n"
        f"**User:** {member.mention} (`{member}` · ID: `{member.id}`)\n"
        f"**Left:** {elapsed_str} after automod timeout\n"
        f"**Original rule:** {rule}"
    )
    await mod_channel.send(alert)
    log.info("Leave alert sent for %s — left %s after timeout", member, elapsed_str)
