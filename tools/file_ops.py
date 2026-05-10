"""File operation tools: read, write, grep, glob, revert.

Every write automatically snapshots the previous content so 'revert' can undo.
"""

import os
import glob as _glob
import subprocess
from pathlib import Path
from typing import Dict, Optional

# In-memory snapshot store: {path: previous_content_or_None}
_SNAPSHOTS: Dict[str, Optional[str]] = {}

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
                _SNAPSHOTS[path] = f.read()
            action = "updated"
        else:
            _SNAPSHOTS[path] = None
            action = "created"

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"{action}: {path} (snapshot saved — use revert to undo)"
    except Exception as e:
        return f"Error writing {path}: {e}"


# ── Grep ────────────────────────────────────────────────


def run_grep(pattern: str, path: str = ".", recursive: bool = True) -> str:
    """Search for a regex pattern in files."""
    try:
        flags = ["-r"] if recursive else []
        result = subprocess.run(
            ["grep", "-n", *flags, pattern, path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return ((result.stdout + result.stderr).strip() or "(no matches)")[:10000]
    except FileNotFoundError:
        try:
            cmd = f'findstr /S /N "{pattern}" "{path}\\*.py" "{path}\\*.js" "{path}\\*.md"'
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            return ((result.stdout + result.stderr).strip() or "(no matches)")[:10000]
        except Exception as e:
            return f"Error: grep/findstr failed: {e}"
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
    """Undo the last write to a file by restoring the snapshot."""
    if path not in _SNAPSHOTS:
        return f"Error: no snapshot for {path}"

    original = _SNAPSHOTS.pop(path)

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
        name="grep",
        description="Search for a regex pattern in files under a path.",
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
        description="Restore a file to its state before the last write.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=lambda inp: run_revert(inp["path"]),
    )
