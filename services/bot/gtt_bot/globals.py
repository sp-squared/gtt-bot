import time

retriever = None
_start_time = time.time()
guild_thread_mode: dict[int, bool] = {}
anthropic_cooldowns: dict[int, float] = {}
local_cooldowns: dict[int, float] = {}
query_terms: list[str] = []
thread_owners: dict[int, int] = {}  # thread_id → user_id
recent_timeouts: dict[int, tuple[float, str]] = {}  # member_id → (timestamp, rule)
