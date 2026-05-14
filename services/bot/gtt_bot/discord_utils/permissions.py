import discord

from gtt_bot.config import REQUIRED_ROLE, ALLOWED_CHANNELS, ALLOWED_GUILDS, COOLDOWN_EXEMPT_ROLE


def has_required_role(member: discord.Member) -> bool:
    if not REQUIRED_ROLE:
        return True
    return any(role.name == REQUIRED_ROLE for role in member.roles)


def is_cooldown_exempt(user: discord.abc.User) -> bool:
    from gtt_bot.config import COOLDOWN_EXEMPT_USERS
    if user.id in COOLDOWN_EXEMPT_USERS:
        return True
    if COOLDOWN_EXEMPT_ROLE and isinstance(user, discord.Member):
        return any(role.name == COOLDOWN_EXEMPT_ROLE for role in user.roles)
    return False


def can_be_timed_out(member: discord.Member) -> bool:
    """Returns False for admins and members with roles above the bot."""
    if member.guild_permissions.administrator:
        return False
    me = member.guild.me
    if me and member.top_role >= me.top_role:
        return False
    return True


def is_allowed_channel(channel) -> bool:
    """Check if channel or its parent (for threads) is in ALLOWED_CHANNELS."""
    if not ALLOWED_CHANNELS:
        return True
    if channel.id in ALLOWED_CHANNELS:
        return True
    # Thread — check parent channel
    if isinstance(channel, discord.Thread) and channel.parent_id in ALLOWED_CHANNELS:
        return True
    return False


def is_allowed_guild(guild_id: int) -> bool:
    return not ALLOWED_GUILDS or guild_id in ALLOWED_GUILDS
