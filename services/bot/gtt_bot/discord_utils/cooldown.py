import time


def check_cooldown(user_id: int, store: dict, seconds: int) -> float:
    now = time.time()
    remaining = seconds - (now - store.get(user_id, 0))
    return max(0.0, remaining)
