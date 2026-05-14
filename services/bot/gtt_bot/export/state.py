import json
from pathlib import Path

_STATE_FILE = Path("/exports/export-state.json")


def load_export_state() -> tuple[dict, bool]:
    """Returns (state_dict, is_bootstrap). is_bootstrap is True when no state exists."""
    if not _STATE_FILE.exists():
        return {}, True
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8")), False
    except Exception:
        return {}, True


def save_export_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
