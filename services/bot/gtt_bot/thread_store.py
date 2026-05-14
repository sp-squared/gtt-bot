import json
import logging
import os

import gtt_bot.globals as G

log = logging.getLogger("bot")

_PATH = "/exports/.thread_owners.json"


def load():
    try:
        with open(_PATH) as f:
            data = json.load(f)
        G.thread_owners = {int(k): int(v) for k, v in data.items()}
        log.info("thread_store: loaded %d entries", len(G.thread_owners))
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("thread_store: failed to load")


def save():
    try:
        with open(_PATH, "w") as f:
            json.dump({str(k): v for k, v in G.thread_owners.items()}, f)
    except Exception:
        log.exception("thread_store: failed to save")


def register(thread_id: int, user_id: int):
    G.thread_owners[thread_id] = user_id
    save()
