"""Context compression: keep conversations from exceeding model limits.

Implements a 3-layer strategy:
1. Verbatim: Last N messages kept exactly as-is.
2. Summarization: Older messages are condensed by the LLM into a summary.
3. Persistence: The summary is written to .agent_memory.md on disk.
"""

import os
from pathlib import Path
from typing import List, Dict, Any

from config.settings import client, MODEL

COMPRESS_THRESHOLD = 40_000  # chars
KEEP_RECENT = 6  # messages
MEMORY_FILE = Path(".agent_memory.md")


def _estimate_size(messages: List[Dict[str, Any]]) -> int:
    """Estimate total character count of message history."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(
                        str(block.get("text", "") or block.get("content", ""))
                    )
                elif hasattr(block, "text"):
                    total += len(block.text or "")
    return total


def _summarize(messages: List[Dict[str, Any]]) -> str:
    """Use the LLM to condense history into a concise summary."""
    text = "\n\n".join(
        f"[{m['role']}]: "
        + (
            m["content"]
            if isinstance(m["content"], str)
            else " ".join(
                (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                for b in (m["content"] if isinstance(m["content"], list) else [])
            )
        )
        for m in messages
    )

    response = client.messages.create(
        model=MODEL,
        system=(
            "You are a context compressor. Summarize the conversation history. "
            "Retain critical decisions, file paths, code changes, and pending tasks. "
            "Ignore trivial back-and-forth."
        ),
        messages=[
            {"role": "user", "content": f"Summarize this history:\n\n{text[:20000]}"}
        ],
        max_tokens=2000,
    )
    return "".join(
        block.text for block in response.content if hasattr(block, "text")
    )


def maybe_compress(messages: List[Dict[str, Any]]) -> bool:
    """Check if compression is needed and perform it in-place.

    Returns True if compression occurred.
    """
    if _estimate_size(messages) < COMPRESS_THRESHOLD:
        return False
    if len(messages) <= KEEP_RECENT:
        return False

    print("\033[90m  [compress] Context large — condensing older history...\033[0m")
    old = messages[:-KEEP_RECENT]
    recent = messages[-KEEP_RECENT:]

    summary = _summarize(old)

    try:
        MEMORY_FILE.write_text(
            f"# Agent Context Memory\n*Working dir: {os.getcwd()}*\n\n{summary}\n",
            encoding="utf-8",
        )
    except Exception as e:
        print(f"\033[31m  [error] Failed to persist memory: {e}\033[0m")

    messages.clear()
    messages.append({
        "role": "user",
        "content": f"[Context summary of previous turns]:\n\n{summary}",
    })
    messages.append({
        "role": "assistant",
        "content": "Understood. I have integrated the summary into my current context.",
    })
    messages.extend(recent)

    print(
        f"\033[90m  [compress] Done. Collapsed {len(old)} messages into 1 summary.\033[0m"
    )
    return True
