import gtt_bot.globals as G
from gtt_bot.config import DEFAULT_USE_THREADS


def get_thread_mode(guild_id: int) -> bool:
    return G.guild_thread_mode.get(guild_id, DEFAULT_USE_THREADS)


def set_thread_mode(guild_id: int, enabled: bool) -> None:
    G.guild_thread_mode[guild_id] = enabled
