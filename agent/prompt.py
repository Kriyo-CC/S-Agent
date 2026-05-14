"""System prompt builder — layered, single-responsibility chunks.

Layer 1: Identity, Role & Constraints
Layer 2: Environment (cwd, datetime)
Layer 3: Dynamic Context (UserSpace file inventory, skill list)
Layer 4: Memories (loaded from memory/ directory)
Layer 5: Available Sub-Agents (from agents/ directory)
"""

import os
from datetime import datetime

from tools.skill import discover_skills
from tools.ledger import run_ledger_list
from tools.subagent import discover_agents
from agent.memory import load_memories, format_memories


# ═══════════════════════════════════════════════════════════════
# Layer 1: Identity, Role & Constraints
# ═══════════════════════════════════════════════════════════════

def _layer_identity() -> str:
    return (
        "You are a personal AI secretary (个人AI秘书). "
        "You help the user manage structured personal data (expenses, tasks, "
        "memos, passwords, fitness, coupons, etc.) stored as markdown files "
        "in the UserSpace/ directory. You also assist with coding tasks, "
        "file operations, and system automation on the local Linux environment.\n"
        "Prefer structured file tools (read/write/grep/glob) over raw bash. "
        "MCP tools are prefixed mcp__<server>__<tool>. "
        "When creating a NEW memory file, first read UserSpace/.formats.md "
        "for the classification guide and default format templates."
    )


# ═══════════════════════════════════════════════════════════════
# Layer 2: Environment
# ═══════════════════════════════════════════════════════════════

def _layer_environment() -> str:
    now = datetime.now()
    return (
        f"Working directory: {os.getcwd()}\n"
        f"Current datetime: {now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"({now.strftime('%A')}), Week {now.strftime('%W')}"
    )


# ═══════════════════════════════════════════════════════════════
# Layer 3: Dynamic Context
# ═══════════════════════════════════════════════════════════════

def _layer_dynamic_context() -> str:
    skills = discover_skills()
    skill_index = (
        "\n".join(f"  - {n}: {d}" for n, d in skills.items())
        or "  (none installed)"
    )
    ledger_context = run_ledger_list()

    return (
        f"\n{ledger_context}\n\n"
        f"── Available Skills ──\n{skill_index}"
    )


# ═══════════════════════════════════════════════════════════════
# Layer 4: Stored Memories
# ═══════════════════════════════════════════════════════════════

def _layer_memories() -> str:
    """Load memories from memory/ directory and format for prompt injection."""
    memories = load_memories()
    return format_memories(memories)


# ═══════════════════════════════════════════════════════════════
# Layer 5: Available Sub-Agents
# ═══════════════════════════════════════════════════════════════

def _layer_agents() -> str:
    """List available sub-agents that can be spawned via spawn_subagent."""
    agents = discover_agents()
    if not agents:
        return "── Available Sub-Agents ──\n  (none)"

    lines = ["── Available Sub-Agents ──"]
    for name, desc in agents.items():
        lines.append(f"  - {name}: {desc or '(no description)'}")
    lines.append(
        "Use spawn_subagent(agent_name, prompt) to delegate a subtask."
    )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Assembly
# ═══════════════════════════════════════════════════════════════

def build_system_prompt() -> str:
    """Compose the full system prompt from layered chunks."""
    return "\n\n".join([
        _layer_identity(),
        _layer_environment(),
        _layer_dynamic_context(),
        _layer_memories(),
        _layer_agents(),
    ])
