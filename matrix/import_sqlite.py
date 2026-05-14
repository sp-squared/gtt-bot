#!/usr/bin/env python3
"""
GTT Discord → Matrix SQLite Direct Import v2
Writes proper state events before messages so Synapse can reconstruct room state.

Usage:
    Phase 1 (Synapse running): python import_sqlite.py
    Phase 2 (Synapse stopped): python import_sqlite.py --skip-rooms

Requirements:
    pip install requests
"""

import json
import os
import re
import sqlite3
import sys
import time
import uuid
import requests
from pathlib import Path
from datetime import datetime

# --- Config ---
SYNAPSE_URL = "http://localhost:8008"
ADMIN_USER = "gttadmin"
ADMIN_PASSWORD = "gttadmin123"
DB_PATH = Path("homeserver.db")
EXPORTS_DIR = Path("C:/Users/colin/Documents/Merly/gtt-exports/latest")
SPACE_NAME = "Goju Tech Talk Archive"
SPACE_ALIAS = "gtt-archive"
SERVER_NAME = "gtt.local"
PROGRESS_FILE = Path("import-sqlite-progress.json")


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login():
    resp = requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "user": ADMIN_USER,
        "password": ADMIN_PASSWORD
    }, timeout=10)
    if resp.status_code != 200:
        requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/register", json={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "auth": {"type": "m.login.dummy"}
        }, timeout=10)
        resp = requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/login", json={
            "type": "m.login.password",
            "user": ADMIN_USER,
            "password": ADMIN_PASSWORD
        }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_or_create_space(token):
    alias_encoded = f"%23{SPACE_ALIAS}%3A{SERVER_NAME}"
    resp = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/directory/room/{alias_encoded}",
        headers=headers(token), timeout=10
    )
    if resp.status_code == 200:
        return resp.json()["room_id"]
    resp = requests.post(
        f"{SYNAPSE_URL}/_matrix/client/v3/createRoom",
        headers=headers(token),
        json={
            "name": SPACE_NAME,
            "room_alias_name": SPACE_ALIAS,
            "topic": "Goju Tech Talk Discord Archive",
            "creation_content": {"type": "m.space"},
            "preset": "public_chat"
        }, timeout=10
    )
    resp.raise_for_status()
    return resp.json()["room_id"]


def get_or_create_room(token, channel_name):
    alias = re.sub(r"[^a-z0-9-]", "-", channel_name.lower()).strip("-")[:50]
    full_alias = f"gtt-{alias}"
    alias_encoded = f"%23{full_alias}%3A{SERVER_NAME}"
    resp = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/directory/room/{alias_encoded}",
        headers=headers(token), timeout=10
    )
    if resp.status_code == 200:
        return resp.json()["room_id"]
    resp = requests.post(
        f"{SYNAPSE_URL}/_matrix/client/v3/createRoom",
        headers=headers(token),
        json={
            "name": f"#{channel_name}",
            "room_alias_name": full_alias,
            "topic": f"Discord #{channel_name} archive",
            "preset": "public_chat"
        }, timeout=10
    )
    resp.raise_for_status()
    return resp.json()["room_id"]


def add_to_space(token, space_id, room_id):
    requests.put(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{space_id}/state/m.space.child/{room_id}",
        headers=headers(token),
        json={"via": [SERVER_NAME], "suggested": False},
        timeout=10
    )


def make_event_id():
    return f"${uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"


def parse_ts(timestamp):
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def format_message(msg):
    content = msg.get("content", "") or ""
    author = msg.get("author", "Unknown")
    attachments = msg.get("attachments", [])
    reactions = msg.get("reactions", {})
    reply_to = msg.get("reply_to_id")

    parts = [f"[{author}]"]
    if reply_to:
        parts.append("↩ reply")
    if content:
        parts.append(content)
    for att in attachments:
        fname = att.get("filename", "file") if isinstance(att, dict) else str(att)
        url = att.get("url", "") if isinstance(att, dict) else ""
        parts.append(f"📎 {fname}" + (f": {url}" if url else ""))
    if reactions:
        rxn_str = " ".join(f"{e}({len(u)})" for e, u in reactions.items())
        parts.append(f"[{rxn_str}]")
    return " ".join(parts)


def get_db_counters(db, room_id):
    """Get current max stream_ordering, topological_ordering, depth for a room."""
    cur = db.execute("SELECT COALESCE(MAX(stream_ordering), 0) FROM events")
    global_stream = cur.fetchone()[0] or 0

    cur = db.execute("SELECT COALESCE(MAX(topological_ordering), 0) FROM events WHERE room_id=?", (room_id,))
    topo = cur.fetchone()[0] or 0

    cur = db.execute("SELECT COALESCE(MAX(depth), 0) FROM events WHERE room_id=?", (room_id,))
    depth = cur.fetchone()[0] or 0

    return global_stream, topo, depth


def insert_event(db, counters, room_id, user_id, event_type, content, state_key=None, ts_ms=None):
    """Insert a single event into events and event_json tables."""
    global_stream, topo, depth = counters
    global_stream += 1
    topo += 1
    depth += 1

    if ts_ms is None:
        ts_ms = int(time.time() * 1000)

    event_id = make_event_id()
    content_json = json.dumps(content)

    full_event = json.dumps({
        "type": event_type,
        "room_id": room_id,
        "sender": user_id,
        "content": content,
        "origin_server_ts": ts_ms,
        "event_id": event_id,
        "auth_events": [],
        "prev_events": [],
        "depth": depth,
        "hashes": {},
        "signatures": {},
        **({"state_key": state_key} if state_key is not None else {}),
    })

    db.execute(
        """INSERT OR IGNORE INTO events
           (stream_ordering, topological_ordering, event_id, type, room_id,
            content, unrecognized_keys, processed, outlier, depth,
            origin_server_ts, received_ts, sender, contains_url,
            instance_name, state_key, rejection_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (global_stream, topo, event_id, event_type, room_id,
         content_json, "{}", 1, 0, depth,
         ts_ms, ts_ms, user_id, 0,
         "master", state_key, None)
    )

    db.execute(
        "INSERT OR IGNORE INTO event_json (event_id, room_id, internal_metadata, json, format_version) VALUES (?,?,?,?,1)",
        (event_id, room_id, "{}", full_event)
    )

    # Update state table if this is a state event
    if state_key is not None:
        db.execute(
            """INSERT OR REPLACE INTO current_state_events
               (room_id, type, state_key, event_id, membership)
               VALUES (?,?,?,?,?)""",
            (room_id, event_type, state_key, event_id,
             content.get("membership") if event_type == "m.room.member" else None)
        )

    counters[0] = global_stream
    counters[1] = topo
    counters[2] = depth

    return event_id


def insert_state_events(db, room_id, user_id, channel_name, ts_ms):
    """Insert the required state events for a room."""
    counters = list(get_db_counters(db, room_id))

    # m.room.create
    insert_event(db, counters, room_id, user_id, "m.room.create",
        {"creator": user_id, "room_version": "10"},
        state_key="", ts_ms=ts_ms - 5000)

    # m.room.member (admin joins)
    insert_event(db, counters, room_id, user_id, "m.room.member",
        {"membership": "join", "displayname": ADMIN_USER},
        state_key=user_id, ts_ms=ts_ms - 4000)

    # m.room.power_levels
    insert_event(db, counters, room_id, user_id, "m.room.power_levels",
        {"users": {user_id: 100}, "users_default": 0,
         "events": {}, "events_default": 0,
         "state_default": 50, "ban": 50, "kick": 50,
         "redact": 50, "invite": 0},
        state_key="", ts_ms=ts_ms - 3000)

    # m.room.join_rules
    insert_event(db, counters, room_id, user_id, "m.room.join_rules",
        {"join_rule": "public"},
        state_key="", ts_ms=ts_ms - 2000)

    # m.room.history_visibility
    insert_event(db, counters, room_id, user_id, "m.room.history_visibility",
        {"history_visibility": "shared"},
        state_key="", ts_ms=ts_ms - 1000)

    # m.room.name
    insert_event(db, counters, room_id, user_id, "m.room.name",
        {"name": f"#{channel_name}"},
        state_key="", ts_ms=ts_ms - 500)

    db.commit()
    return counters


def insert_messages_sqlite(db, room_id, messages, user_id, initial_counters):
    """Insert messages directly into events and event_json tables."""
    counters = list(initial_counters)
    inserted = 0
    events_batch = []
    json_batch = []

    for msg in messages:
        text = format_message(msg)
        ts_ms = parse_ts(msg.get("timestamp", ""))
        event_id = make_event_id()

        counters[0] += 1  # global stream
        counters[1] += 1  # topo
        counters[2] += 1  # depth

        content_json = json.dumps({"msgtype": "m.text", "body": text})
        full_event = json.dumps({
            "type": "m.room.message",
            "room_id": room_id,
            "sender": user_id,
            "content": {"msgtype": "m.text", "body": text},
            "origin_server_ts": ts_ms,
            "event_id": event_id,
            "auth_events": [],
            "prev_events": [],
            "depth": counters[2],
            "hashes": {},
            "signatures": {},
        })

        events_batch.append((
            counters[0], counters[1], event_id, "m.room.message", room_id,
            content_json, "{}", 1, 0, counters[2],
            ts_ms, ts_ms, user_id, 0, "master", None, None
        ))
        json_batch.append((event_id, room_id, "{}", full_event))

        if len(events_batch) >= 500:
            db.executemany(
                """INSERT OR IGNORE INTO events
                   (stream_ordering, topological_ordering, event_id, type, room_id,
                    content, unrecognized_keys, processed, outlier, depth,
                    origin_server_ts, received_ts, sender, contains_url,
                    instance_name, state_key, rejection_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                events_batch
            )
            db.executemany(
                "INSERT OR IGNORE INTO event_json (event_id, room_id, internal_metadata, json, format_version) VALUES (?,?,?,?,1)",
                json_batch
            )
            db.commit()
            inserted += len(events_batch)
            events_batch = []
            json_batch = []

    if events_batch:
        db.executemany(
            """INSERT OR IGNORE INTO events
               (stream_ordering, topological_ordering, event_id, type, room_id,
                content, unrecognized_keys, processed, outlier, depth,
                origin_server_ts, received_ts, sender, contains_url,
                instance_name, state_key, rejection_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            events_batch
        )
        db.executemany(
            "INSERT OR IGNORE INTO event_json (event_id, room_id, internal_metadata, json, format_version) VALUES (?,?,?,?,1)",
            json_batch
        )
        db.commit()
        inserted += len(events_batch)

    return inserted


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}


def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def main():
    skip_rooms = "--skip-rooms" in sys.argv
    print("GTT Discord → Matrix SQLite Direct Import v2")
    print("=" * 50)

    if not DB_PATH.exists():
        print(f"✗ Database not found at {DB_PATH}")
        print("  Start Synapse once first: docker compose up synapse -d")
        print("  Then stop it: docker compose stop synapse")
        return

    progress = load_progress()
    json_files = sorted([f for f in EXPORTS_DIR.glob("*.json") if not f.name.startswith("members")])
    print(f"✓ Found {len(json_files)} channel exports")
    room_map = {k: v["room_id"] for k, v in progress.items() if "room_id" in v}

    # Phase 1 — Create rooms via API
    print(f"\nPhase 1: Creating rooms via API")
    if skip_rooms:
        print(f"  Skipping (--skip-rooms) — loaded {len(room_map)} room IDs from progress")
    else:
        try:
            requests.get(f"{SYNAPSE_URL}/_matrix/client/versions", timeout=5).raise_for_status()
            print(f"✓ Synapse is running")
        except Exception:
            print(f"✗ Synapse not reachable. Start it first: docker compose start synapse")
            return

        token = login()
        print(f"✓ Logged in as @{ADMIN_USER}:{SERVER_NAME}")
        space_id = get_or_create_space(token)
        print(f"✓ Space ready: {space_id}")

        print("\nCreating rooms...")
        for idx, json_file in enumerate(json_files):
            channel_name = json_file.stem
            if channel_name in progress and "room_id" in progress[channel_name]:
                room_map[channel_name] = progress[channel_name]["room_id"]
                print(f"  [{idx+1}/{len(json_files)}] #{channel_name} — exists")
                continue
            try:
                room_id = get_or_create_room(token, channel_name)
                add_to_space(token, space_id, room_id)
                room_map[channel_name] = room_id
                progress[channel_name] = {"room_id": room_id, "complete": False}
                save_progress(progress)
                print(f"  [{idx+1}/{len(json_files)}] #{channel_name} → {room_id}")
            except Exception as e:
                print(f"  [{idx+1}/{len(json_files)}] #{channel_name} — ERROR: {e}")

    # Phase 2 — Direct SQLite import
    print(f"\nPhase 2: Direct SQLite import")
    print(f"⚠️  STOP SYNAPSE NOW before continuing:")
    print(f"   docker compose stop synapse")
    input("\nPress ENTER when Synapse is stopped...")

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    # Get admin user ID
    cur = db.execute("SELECT name FROM users WHERE name LIKE ? LIMIT 1", (f"@{ADMIN_USER}:%",))
    row = cur.fetchone()
    user_id = row[0] if row else f"@{ADMIN_USER}:{SERVER_NAME}"
    print(f"✓ Admin user: {user_id}")

    # Check current_state_events table exists
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "current_state_events" not in tables:
        print("✗ current_state_events table not found — is this a Synapse database?")
        db.close()
        return

    total_inserted = 0

    for idx, json_file in enumerate(json_files):
        channel_name = json_file.stem
        room_id = room_map.get(channel_name)

        if not room_id:
            print(f"[{idx+1}/{len(json_files)}] #{channel_name} — no room ID, skipping")
            continue

        if progress.get(channel_name, {}).get("complete"):
            count = progress[channel_name].get("count", 0)
            print(f"[{idx+1}/{len(json_files)}] #{channel_name} — already done ({count} msgs)")
            total_inserted += count
            continue

        print(f"[{idx+1}/{len(json_files)}] #{channel_name}", end=" ", flush=True)

        try:
            with open(json_file, encoding="utf-8") as f:
                messages = json.load(f)

            # Get first message timestamp for state events
            first_ts = parse_ts(messages[0].get("timestamp", "")) if messages else int(time.time() * 1000)

            start = time.time()

            # Insert state events first
            counters = insert_state_events(db, room_id, user_id, channel_name, first_ts)

            # Insert messages
            inserted = insert_messages_sqlite(db, room_id, messages, user_id, counters)
            elapsed = time.time() - start

            rate = int(inserted / max(elapsed, 0.01))
            print(f"— {inserted:,} msgs in {elapsed:.1f}s ({rate:,}/s)")
            total_inserted += inserted

            progress[channel_name]["complete"] = True
            progress[channel_name]["count"] = inserted
            save_progress(progress)

        except KeyboardInterrupt:
            print("\nInterrupted — progress saved.")
            db.close()
            return
        except Exception as e:
            print(f"— ERROR: {e}")
            import traceback
            traceback.print_exc()

    db.close()

    print(f"\n{'=' * 50}")
    print(f"✓ Import complete — {total_inserted:,} messages total")
    print(f"\nRestart Synapse:")
    print(f"   docker compose start synapse")
    print(f"\nThen open Element: http://localhost:3000")
    print(f"Login: @{ADMIN_USER}:{SERVER_NAME} / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    main()