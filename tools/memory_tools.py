"""Memory tools: persist and retrieve structured memory.

Each memory is stored as a markdown file in the memory/ directory with
YAML frontmatter for metadata (name, description, type, timestamps).

Tools:
  remember(key, value)    — Save or update a memory
  forget(key)             — Delete a memory by key
  list_memories()         — List all stored memories
"""

import re
import time
from pathlib import Path

MEMORY_DIR = Path("memory")


def _slugify(key: str) -> str:
    """Convert a key string to a safe filename slug."""
    slug = key.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = slug[:80] or "memory"
    return slug


def _memory_path(key: str) -> Path:
    """Get the filesystem path for a memory by key."""
    return MEMORY_DIR / f"{_slugify(key)}.md"


def _read_frontmatter(path: Path) -> dict:
    """Read YAML frontmatter from a markdown file."""
    meta = {"name": path.stem, "type": "note"}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return meta

    # Parse simple frontmatter (---\nkey: value\n...\n---)
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return meta

    for line in m.group(1).splitlines():
        kv = re.match(r"^\s*(\w+)\s*:\s*(.+)\s*$", line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip()

    return meta


def run_remember(key: str, value: str, description: str = "") -> str:
    """Save or update a memory.

    Args:
        key: Memory identifier (slugified to create filename).
        value: Content to store in the memory.
        description: Optional short description.

    Returns:
        Confirmation message.
    """
    if not key or not key.strip():
        return "Error: key cannot be empty."

    slug = _slugify(key)
    path = _memory_path(key)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    exists = path.exists()

    # Read existing frontmatter to preserve created date
    if exists:
        existing = _read_frontmatter(path)
        created = existing.get("created", now)
        current_type = existing.get("type", "note")
        current_desc = existing.get("description", description)
    else:
        created = now
        current_type = "note"
        current_desc = description or ""

    content = (
        f"---\n"
        f"name: {slug}\n"
        f"description: {current_desc}\n"
        f"type: {current_type}\n"
        f"created: {created}\n"
        f"updated: {now}\n"
        f"---\n"
        f"\n"
        f"# {key.strip()}\n"
        f"\n"
        f"{value.strip()}\n"
    )

    try:
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"Error saving memory: {e}"

    action = "updated" if exists else "saved"
    return f"Memory '{slug}' {action}."


def run_forget(key: str) -> str:
    """Delete a memory by key.

    Args:
        key: Memory identifier. Supports exact slug or partial match.

    Returns:
        Confirmation message.
    """
    if not key or not key.strip():
        return "Error: key cannot be empty."

    path = _memory_path(key)
    if path.exists():
        try:
            path.unlink()
            slug = _slugify(key)
            return f"Memory '{slug}' forgotten."
        except Exception as e:
            return f"Error forgetting memory: {e}"

    # Try partial match in filename
    slug = _slugify(key)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    for f in MEMORY_DIR.glob("*.md"):
        if slug in f.stem:
            try:
                f.unlink()
                return f"Memory '{f.stem}' forgotten."
            except Exception as e:
                return f"Error forgetting memory: {e}"

    return f"Error: no memory found for key '{key}'."


def run_list_memories() -> str:
    """List all stored memories with metadata."""
    if not MEMORY_DIR.exists():
        return "(no memories stored.)"

    files = sorted(MEMORY_DIR.glob("*.md"))
    if not files:
        return "(no memories stored.)"

    lines = ["Stored memories:"]
    for f in files:
        meta = _read_frontmatter(f)
        desc = f" — {meta.get('description', '')}" if meta.get("description") else ""
        updated = meta.get("updated", "")
        updated_str = f" [{updated}]" if updated else ""
        lines.append(f"  - {f.stem}{desc}{updated_str}")

    return "\n".join(lines)


def register_memory_tools(registry) -> None:
    registry.register(
        name="remember",
        description=(
            "Save a piece of information to memory. Memories persist across "
            "sessions and are automatically loaded into context each turn. "
            "Use this for user preferences, project decisions, or important facts."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "A short identifier for the memory (e.g. 'user-name', 'coding-style').",
                },
                "value": {
                    "type": "string",
                    "description": "The content to remember.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional short description shown in list_memories.",
                },
            },
            "required": ["key", "value"],
        },
        handler=lambda inp: run_remember(
            inp["key"], inp["value"], inp.get("description", "")
        ),
    )

    registry.register(
        name="forget",
        description=(
            "Delete a memory by key. Use list_memories to see available keys."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the memory to forget.",
                },
            },
            "required": ["key"],
        },
        handler=lambda inp: run_forget(inp["key"]),
    )

    registry.register(
        name="list_memories",
        description=(
            "List all stored memories with their keys, descriptions, and last "
            "updated timestamps."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
        handler=lambda inp: run_list_memories(),
    )
