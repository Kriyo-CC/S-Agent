"""Ledger tool: scans UserSpace/ so the system prompt knows what memory
documents exist and what format each one uses.

This is kept intentionally minimal — a single list tool. All actual writing
is done via the general `read` and `write` tools.
"""

from pathlib import Path

USERSPACE = Path("UserSpace")


def run_ledger_list() -> str:
    """List all memory documents in UserSpace with their headers.

    Used by the system prompt builder to inject UserSpace context dynamically
    so the agent always knows what documents exist and their formats.
    """
    USERSPACE.mkdir(parents=True, exist_ok=True)
    files = sorted(USERSPACE.glob("*.md"))

    if not files:
        return "UserSpace/ is empty — no memory documents yet."

    parts = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        header = "\n".join(text.split("\n")[:8])
        parts.append(f"**{f.name}**:\n```\n{header}\n```")

    return "\n\n".join(parts)


def register_ledger_tools(registry) -> None:
    registry.register(
        name="ledger_list",
        description=(
            "List all memory documents in UserSpace/ with their headers/format. "
            "Call this FIRST to see existing documents and fields before using "
            "read/write to modify them."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=lambda _inp: run_ledger_list(),
    )
