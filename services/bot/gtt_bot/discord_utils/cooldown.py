import time


def check_cooldown(user_id: int, store: dict, seconds: int) -> float:
    now = time.time()
    remaining = seconds - (now - store.get(user_id, 0))
    return max(0.0, remaining)


def prune_cooldowns(store: dict, window: int) -> int:
    """Drop entries whose cooldown has expired. Returns the number pruned."""
    now = time.time()
    stale = [uid for uid, ts in store.items() if now - ts > window]
    for uid in stale:
        store.pop(uid, None)
    return len(stale)
