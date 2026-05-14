"""File operation tools: read, write, edit, grep, glob, revert.

Write and Edit automatically snapshot previous content so revert can undo.
Snapshots are saved to .snapshots/ via tools/snapshot.py (persistent).
"""

import os
import glob as _glob
import subprocess
from pathlib import Path
from typing import Optional

from tools.snapshot import save_snapshot, restore_snapshot, has_snapshot

# ── Read ────────────────────────────────────────────────


def run_read(
    path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
) -> str:
    """Read a file with optional line-range and line numbering."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        start_idx = (start_line or 1) - 1
        end_idx = end_line or len(lines)

        numbered = "".join(
            f"{start_idx + 1 + i:4d}\t{line}"
            for i, line in enumerate(lines[start_idx:end_idx])
        )
        return numbered[:50000] or "(empty file)"
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


# ── Write ───────────────────────────────────────────────


def run_write(path: str, content: str) -> str:
    """Write content to a file, snapshotting previous content for revert."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                prev = f.read()
            save_snapshot(path, prev)
            action = "updated"
        else:
            save_snapshot(path, None)  # new file, no previous content
            action = "created"

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"{action}: {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


# ── Edit ────────────────────────────────────────────────


def run_edit(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by replacing exactly one occurrence of old_string.

    Fails with a clear message if old_string is not found (0 matches)
    or if it appears multiple times (>1 matches).

    Snapshots the file before making any change.
    """
    try:
        content = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"

    count = content.count(old_string)
    if count == 0:
        return "Error: string not found. Ensure the exact string appears in the file."
    if count > 1:
        return (
            f"Error: found {count} occurrences of the string. "
            "Please include more surrounding context to make the match unique."
        )

    # Snapshot before editing
    save_snapshot(path, content)

    content = content.replace(old_string, new_string, 1)
    try:
        Path(path).write_text(content, encoding="utf-8")
        return f"edited: {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


# ── Grep ────────────────────────────────────────────────


def run_grep(pattern: str, path: str = ".", recursive: bool = True) -> str:
    """Search for a regex pattern in files.

    Uses ripgrep (rg) if available, falls back to system grep.
    """
    recursive_flag = ["-r"] if recursive else []

    # Try ripgrep first (faster, respects .gitignore)
    try:
        result = subprocess.run(
            ["rg", "-n", *recursive_flag, pattern, path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:10000] if output else "(no matches)"
    except FileNotFoundError:
        pass  # rg not installed, fall through to grep
    except subprocess.TimeoutExpired:
        return "Error: rg timeout"
    except Exception:
        pass

    # Fallback: system grep
    try:
        result = subprocess.run(
            ["grep", "-n", *recursive_flag, pattern, path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:10000] if output else "(no matches)"
    except FileNotFoundError:
        return "Error: neither rg nor grep found on system"
    except subprocess.TimeoutExpired:
        return "Error: grep timeout"
    except Exception as e:
        return f"Error: {e}"


# ── Glob ────────────────────────────────────────────────


def run_glob(pattern: str) -> str:
    """Find files matching a glob pattern (e.g. '**/*.py')."""
    matches = _glob.glob(pattern, recursive=True)
    if not matches:
        return "(no matches)"
    return "\n".join(sorted(matches)[:200])


# ── Revert ──────────────────────────────────────────────


def run_revert(path: str) -> str:
    """Undo the last write/edit to a file by restoring the snapshot."""
    if not has_snapshot(path):
        return f"Error: no snapshot for {path}"

    original = restore_snapshot(path)

    if original is None:
        try:
            os.remove(path)
            return f"reverted: deleted {path} (was a new file)"
        except Exception as e:
            return f"Error deleting {path}: {e}"
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(original)
            return f"reverted: {path}"
        except Exception as e:
            return f"Error reverting {path}: {e}"


# ── Registration ─────────────────────────────────────────


def register_file_tools(registry) -> None:
    registry.register(
        name="read",
        description="Read a file. Optional start_line/end_line for a range (1-indexed).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
        handler=lambda inp: run_read(
            inp["path"], inp.get("start_line"), inp.get("end_line")
        ),
    )
    registry.register(
        name="write",
        description="Write content to a file. Snapshots previous content automatically.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=lambda inp: run_write(inp["path"], inp["content"]),
    )
    registry.register(
        name="edit",
        description=(
            "Edit a file by replacing exactly one occurrence of old_string "
            "with new_string. Fails if 0 or >1 matches. Use this instead of "
            "write+read for targeted changes — it's more reliable than "
            "matching on line numbers."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit."},
                "old_string": {
                    "type": "string",
                    "description": "The exact existing text to replace (must match exactly once).",
                },
                "new_string": {
                    "type": "string",
                    "description": "The new text to insert in place of old_string.",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        handler=lambda inp: run_edit(
            inp["path"], inp["old_string"], inp["new_string"]
        ),
    )
    registry.register(
        name="grep",
        description="Search for a regex pattern in files under a path. Uses ripgrep if available.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": True},
            },
            "required": ["pattern"],
        },
        handler=lambda inp: run_grep(
            inp["pattern"], inp.get("path", "."), inp.get("recursive", True)
        ),
    )
    registry.register(
        name="glob",
        description="Find files matching a glob pattern, e.g. '**/*.py'.",
        input_schema={
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
        handler=lambda inp: run_glob(inp["pattern"]),
    )
    registry.register(
        name="revert",
        description=(
            "Restore a file to its state before the last write or edit. "
            "Uses persistent on-disk snapshots (undo works across restarts)."
        ),
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=lambda inp: run_revert(inp["path"]),
    )
