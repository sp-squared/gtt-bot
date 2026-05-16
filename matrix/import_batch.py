#!/usr/bin/env python3
"""
GTT Discord → Matrix Batch Send Import
Uses /_matrix/client/v1/rooms/{roomId}/batchsend for proper historical import.
Chains batches via prev_event_id for correct DAG linking.

Usage:
    python import_batch.py [--resume]

Requirements:
    pip install requests
"""

import json
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
SERVER_NAME = "gtt.local"
AS_TOKEN = "gtt-importer-as-token-change-me"  # Must match import-appservice.yaml
EXPORTS_DIR = Path("C:/Users/colin/Documents/Merly/gtt-exports/latest")
PROGRESS_FILE = Path("import-sqlite-progress.json")

# Batch tuning — larger batches = fewer API calls = faster
# Synapse allows up to 100 events per batch
BATCH_SIZE = 100
# Minimal delay between batches — only slow down on rate limit
BASE_DELAY = 0.05
MAX_RETRIES = 5


def login():
    resp = requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "user": ADMIN_USER,
        "password": ADMIN_PASSWORD
    }, timeout=15)
    if resp.status_code != 200:
        requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/register", json={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "auth": {"type": "m.login.dummy"}
        }, timeout=15)
        resp = requests.post(f"{SYNAPSE_URL}/_matrix/client/v3/login", json={
            "type": "m.login.password",
            "user": ADMIN_USER,
            "password": ADMIN_PASSWORD
        }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data["device_id"]


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def as_headers():
    """Headers using application service token for batch send."""
    return {"Authorization": f"Bearer {AS_TOKEN}", "Content-Type": "application/json"}


def make_event_id():
    return f"${uuid.uuid4().hex}"


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
        rxn_str = " ".join(f"{e}({len(u) if isinstance(u, list) else u})" for e, u in reactions.items())
        parts.append(f"[{rxn_str}]")
    return " ".join(parts)


def get_room_creation_event(token, room_id):
    """Get the room creation event ID to use as the base for batch insertion."""
    resp = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/state/m.room.create/",
        headers=headers(token),
        timeout=15
    )
    if resp.status_code == 200:
        # Get the actual event ID from messages
        resp2 = requests.get(
            f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/messages",
            headers=headers(token),
            params={"dir": "b", "limit": 1},
            timeout=15
        )
        if resp2.status_code == 200:
            chunk = resp2.json().get("chunk", [])
            if chunk:
                return chunk[0]["event_id"]
    return None


def get_latest_event(token, room_id):
    """Get the latest event ID in the room for chaining."""
    resp = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/messages",
        headers=headers(token),
        params={"dir": "b", "limit": 1},
        timeout=15
    )
    if resp.status_code == 200:
        chunk = resp.json().get("chunk", [])
        if chunk:
            return chunk[0]["event_id"]
    return None


def send_batch(token, room_id, events, prev_event_id, insertion_event_id=None):
    """Send a batch of historical events using the batch send API."""
    params = {"prev_event_id": prev_event_id}
    if insertion_event_id:
        params["batch_id"] = insertion_event_id

    user_id = f"@{ADMIN_USER}:{SERVER_NAME}"
    params["user_id"] = user_id
    body = {"events": events, "state_events_at_start": []}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                f"{SYNAPSE_URL}/_matrix/client/unstable/org.matrix.msc2716/rooms/{room_id}/batch_send",
                headers=as_headers(),
                params=params,
                json=body,
                timeout=60
            )
            if resp.status_code == 200:
                data = resp.json()
                ids = data.get("event_ids", data.get("inserted_event_ids", []))
                return data.get("next_batch_id"), ids
            elif resp.status_code == 429:
                retry_ms = resp.json().get("retry_after_ms", 2000)
                time.sleep(retry_ms / 1000)
            elif resp.status_code == 400:
                err = resp.json().get("error", "")
                if "not enabled" in err.lower():
                    print(f"\n  ✗ Batch send API not enabled on this Synapse.")
                    print(f"    Add to homeserver.yaml: experimental_features:")
                    print(f"      msc2716_enabled: true")
                    return None, []
                print(f"\n  ✗ Bad request: {resp.text[:200]}")
                return None, []
            else:
                print(f"\n  ✗ HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(BASE_DELAY * (attempt + 1))
        except requests.exceptions.Timeout:
            print(f"\n  Timeout on attempt {attempt+1}, retrying...")
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"\n  Error: {e}")
            time.sleep(2)

    return None, []


def import_channel_batch(token, room_id, messages, start_index=0):
    """Import all messages for a channel using batch send API."""
    if not messages:
        return 0

    # Get the latest event to chain from
    prev_event_id = get_latest_event(token, room_id)
    if not prev_event_id:
        print(f"  ✗ Could not get latest event for room")
        return 0

    user_id = f"@{ADMIN_USER}:{SERVER_NAME}"
    total = len(messages)
    remaining = messages[start_index:]
    inserted = start_index
    batch_id = None

    for i in range(0, len(remaining), BATCH_SIZE):
        batch_msgs = remaining[i:i + BATCH_SIZE]

        # Build events array
        events = []
        for msg in batch_msgs:
            text = format_message(msg)
            ts_ms = parse_ts(msg.get("timestamp", ""))
            events.append({
                "type": "m.room.message",
                "sender": user_id,
                "origin_server_ts": ts_ms,
                "content": {
                    "msgtype": "m.text",
                    "body": text
                }
            })

        # Send batch
        next_batch_id, event_ids = send_batch(token, room_id, events, prev_event_id, batch_id)

        if event_ids:
            inserted += len(event_ids)
            # Use last inserted event as prev for next batch
            prev_event_id = event_ids[-1]
            batch_id = next_batch_id

        pct = int((inserted / total) * 100)
        print(f"  {inserted}/{total} ({pct}%)", end="\r", flush=True)

        time.sleep(BASE_DELAY)

    print(f"  ✓ {inserted}/{total} messages imported        ")
    return inserted


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}


def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def main():
    resume = "--resume" in sys.argv
    print("GTT Discord → Matrix Batch Import")
    print("=" * 50)

    try:
        requests.get(f"{SYNAPSE_URL}/_matrix/client/versions", timeout=5).raise_for_status()
        print(f"✓ Synapse running at {SYNAPSE_URL}")
    except Exception:
        print(f"✗ Synapse not reachable — start it: docker compose start synapse")
        return

    token, device_id = login()
    print(f"✓ Logged in as @{ADMIN_USER}:{SERVER_NAME}")

    # Check batch send API is enabled
    print("Checking batch send API...")
    test_resp = requests.post(
        f"{SYNAPSE_URL}/_matrix/client/unstable/org.matrix.msc2716/rooms/!test:gtt.local/batch_send",
        headers=headers(token),
        params={"prev_event_id": "$test"},
        json={"events": [], "state_events_at_start": []},
        timeout=10
    )
    if test_resp.status_code == 400:
        err = test_resp.json().get("error", "")
        if "not enabled" in err.lower() or "unknown" in err.lower():
            print(f"✗ Batch send API (MSC2716) not enabled.")
            print(f"\nAdd this to matrix/homeserver.yaml:")
            print(f"  experimental_features:")
            print(f"    msc2716_enabled: true")
            print(f"\nThen restart Synapse: docker compose restart synapse")
            return
    print("✓ Batch send API available")

    json_files = sorted([f for f in EXPORTS_DIR.glob("*.json") if not f.name.startswith("members")])
    print(f"✓ Found {len(json_files)} channel exports\n")

    progress = load_progress()
    total_msgs = 0
    total_rooms = 0

    # Build a lookup by channel name stem — handles unicode emoji key mismatches
    # Map normalized stem → room_id
    room_id_map = {}
    for key, val in progress.items():
        if "room_id" in val:
            room_id_map[key] = val["room_id"]

    for idx, json_file in enumerate(json_files):
        channel_name = json_file.stem
        room_id = room_id_map.get(channel_name)

        if not room_id:
            print(f"[{idx+1}/{len(json_files)}] #{channel_name} — no room ID in progress, skipping")
            print(f"  Run import_sqlite.py first for Phase 1 to create rooms")
            continue

        if resume and progress.get(channel_name, {}).get("complete"):
            count = progress[channel_name].get("count", 0)
            print(f"[{idx+1}/{len(json_files)}] #{channel_name} — skipped ({count} msgs)")
            total_msgs += count
            total_rooms += 1
            continue

        print(f"[{idx+1}/{len(json_files)}] #{channel_name}")

        try:
            with open(json_file, encoding="utf-8") as f:
                messages = json.load(f)

            start_index = progress.get(channel_name, {}).get("imported", 0) if resume else 0
            print(f"  {len(messages)} messages", end=" ", flush=True)

            start = time.time()
            count = import_channel_batch(token, room_id, messages, start_index)
            elapsed = time.time() - start

            progress[channel_name] = {
                "room_id": room_id,
                "imported": count,
                "count": len(messages),
                "complete": count >= len(messages)
            }
            save_progress(progress)
            total_msgs += count
            total_rooms += 1

            rate = int(count / max(elapsed, 0.1))
            print(f"  Done in {elapsed:.1f}s ({rate} msgs/s)")

        except KeyboardInterrupt:
            print("\n\nInterrupted — progress saved. Run with --resume to continue.")
            save_progress(progress)
            return
        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            save_progress(progress)

    print(f"\n{'=' * 50}")
    print(f"✓ Import complete!")
    print(f"  Rooms: {total_rooms}")
    print(f"  Messages: {total_msgs:,}")
    print(f"\nOpen Element: http://localhost:3000")


if __name__ == "__main__":
    main()