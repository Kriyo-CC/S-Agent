"""Memory loader — reads memory files for prompt injection.

This module is the read side of the memory system. It scans the memory/
directory and loads all markdown files for injection into the system prompt.
The write side (save/forget/list) lives in tools/memory_tools.py.

Every turn, prompt.py calls load_memories() and injects the result into
the system prompt via _layer_memories().
"""

from pathlib import Path

MEMORY_DIR = Path("memory")
MAX_MEMORY_CHARS = 2000


def load_memories() -> list[dict]:
    """Load all memory files from the memory/ directory.

    Returns:
        List of dicts with keys: name, description, type, content, created, updated.
        Empty list if memory/ doesn't exist or has no files.
    """
    if not MEMORY_DIR.exists():
        return []

    memories = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == ".gitkeep":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        meta: dict = {"name": f.stem, "type": "note", "description": ""}
        content = text

        # Parse YAML frontmatter (---\nkey: value\n...\n---)
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        meta[k.strip()] = v.strip()
                content = parts[2].strip()

        meta["content"] = content
        memories.append(meta)

    return memories


def format_memories(memories: list[dict]) -> str:
    """Format loaded memories into a compact string for prompt injection.

    Truncates at MAX_MEMORY_CHARS to keep system prompt size bounded.
    Returns an empty string if there are no memories.
    """
    if not memories:
        return ""

    lines = ["── Stored Memories ──"]
    total_chars = 0

    for m in memories:
        name = m.get("name", "?")
        desc = m.get("description", "") or ""
        content = m.get("content", "")
        entry = f"\n[{name}]: {desc}\n{content}\n---"

        total_chars += len(entry)
        if total_chars > MAX_MEMORY_CHARS:
            remaining = len(memories) - len(lines) + 1
            lines.append(f"\n(+ {remaining} more memories — use list_memories to see all)")
            break

        lines.append(entry)

    return "\n".join(lines)
