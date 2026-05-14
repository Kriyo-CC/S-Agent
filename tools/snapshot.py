"""Persistent snapshot module for file undo history.

Snapshots are stored as JSON files in .snapshots/. Each tracked file has
its own snapshot chain (keyed by MD5 of the path), with a max depth of 5.

This module is used by write, edit, and revert tools to enable undo.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

SNAPSHOTS_DIR = Path(".snapshots")
MAX_DEPTH = 5


def _path_hash(file_path: str) -> str:
    """MD5 hash of the absolute file path, used as the snapshot filename."""
    return hashlib.md5(str(Path(file_path).resolve()).encode()).hexdigest()


def _snapshot_file(file_path: str) -> Path:
    """Get the snapshot JSON path for a given original file."""
    return SNAPSHOTS_DIR / f"{_path_hash(file_path)}.json"


def save_snapshot(file_path: str, content: Optional[str]) -> str:
    """Save a snapshot before modifying a file.

    Args:
        file_path: Path to the file being modified.
        content: The file's current content, or None if creating a new file.

    Returns:
        Snapshot ID string.
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = _snapshot_file(file_path)

    history = []
    if snap_path.exists():
        try:
            history = json.loads(snap_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            history = []

    snapshot_id = hashlib.md5(
        f"{file_path}:{time.time()}:{content}".encode()
    ).hexdigest()[:8]

    previous_id = history[-1]["snapshot_id"] if history else None

    entry = {
        "original_path": str(Path(file_path).resolve()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "snapshot_id": snapshot_id,
        "previous_snapshot_id": previous_id,
        "content": content,
    }

    history.append(entry)

    # Keep only the most recent MAX_DEPTH entries
    if len(history) > MAX_DEPTH:
        history = history[-MAX_DEPTH:]

    snap_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return snapshot_id


def restore_snapshot(file_path: str) -> Optional[str]:
    """Restore the most recent snapshot for a file.

    Removes and returns the most recent snapshot entry's content.

    Args:
        file_path: Path to the file to revert.

    Returns:
        Previous file content (str), or None if file was new / no snapshot.
    """
    snap_path = _snapshot_file(file_path)
    if not snap_path.exists():
        return None

    try:
        history = json.loads(snap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None

    if not history:
        return None

    entry = history.pop()

    # Write back remaining history or clean up
    if history:
        snap_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    else:
        snap_path.unlink(missing_ok=True)

    return entry["content"]


def has_snapshot(file_path: str) -> bool:
    """Check if a file has any snapshots."""
    snap_path = _snapshot_file(file_path)
    if not snap_path.exists():
        return False
    try:
        history = json.loads(snap_path.read_text(encoding="utf-8"))
        return len(history) > 0
    except (json.JSONDecodeError, IOError):
        return False


def list_snapshots() -> list:
    """List all snapshots across all files, newest first.

    Returns:
        List of dicts with snapshot metadata (no content field).
    """
    if not SNAPSHOTS_DIR.exists():
        return []

    snapshots = []
    for snap_path in sorted(SNAPSHOTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if snap_path.suffix != ".json":
            continue
        try:
            history = json.loads(snap_path.read_text(encoding="utf-8"))
            for entry in reversed(history):
                snapshots.append({
                    "original_path": entry["original_path"],
                    "timestamp": entry["timestamp"],
                    "snapshot_id": entry["snapshot_id"],
                    "previous_snapshot_id": entry["previous_snapshot_id"],
                })
        except (json.JSONDecodeError, IOError):
            continue

    return snapshots
