"""Append-only log of every deliberation. Useful for spotting patterns in
your indecision over time, and for revisiting the council's verdicts."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_DIR = Path.home() / ".config" / "magi"
JOURNAL_PATH = JOURNAL_DIR / "journal.jsonl"


def _ensure_dir() -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)


def save_entry(
    question: str,
    members: list[str],
    rounds: int,
    outcome: str,
    synthesis: str,
    final_verdicts: dict[str, str],
) -> str:
    """Append a deliberation to the journal. Returns the entry's short id."""
    _ensure_dir()
    entry_id = uuid.uuid4().hex[:8]
    entry = {
        "id": entry_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "members": members,
        "rounds": rounds,
        "outcome": outcome,
        "synthesis": synthesis,
        "final_verdicts": final_verdicts,
        "user_outcome": None,
    }
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry_id


def load_entries(limit: int | None = None) -> list[dict]:
    """Return entries newest first. None limit returns all."""
    if not JOURNAL_PATH.exists():
        return []
    entries = []
    with JOURNAL_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.reverse()
    if limit:
        entries = entries[:limit]
    return entries


def find_entry(id_prefix: str) -> dict | None:
    """Find the first entry whose id starts with id_prefix."""
    for entry in load_entries():
        if entry["id"].startswith(id_prefix):
            return entry
    return None


def set_user_outcome(id_prefix: str, outcome_text: str) -> bool:
    """Mark what the user actually did/didn't do. Rewrites the file.
    Returns True if matched, False otherwise."""
    if not JOURNAL_PATH.exists():
        return False
    entries = []
    matched = False
    with JOURNAL_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not matched and entry.get("id", "").startswith(id_prefix):
                entry["user_outcome"] = outcome_text
                matched = True
            entries.append(entry)
    if matched:
        with JOURNAL_PATH.open("w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
    return matched
