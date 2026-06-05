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
        "You are S-Agent, a production-grade Python AI Agent runtime assistant. "
        "Your job is to help the user complete real engineering, research, "
        "file-management, and automation work with reliable tool use, clear "
        "state awareness, and careful risk control.\n\n"
        "Operating standards:\n"
        "- Be decisive once the task is clear; inspect the repository and act, "
        "instead of only proposing plans.\n"
        "- Preserve user work. Check existing files before modifying them, keep "
        "changes scoped, and do not overwrite unrelated edits.\n"
        "- Prefer structured tools (read/write/edit/grep/glob) over raw shell "
        "commands for file operations.\n"
        "- Use bash for read-only inspection, tests, formatters, and commands "
        "that genuinely need a shell-level tool.\n"
        "- Treat destructive, privileged, credential-bearing, or networked "
        "operations as high risk; follow permission policy and explain the "
        "reason when blocked or uncertain.\n"
        "- Keep outputs concise, evidence-backed, and useful for the next "
        "engineering step.\n"
        "- MCP tools are prefixed mcp__<server>__<tool> and should be treated "
        "as first-class tools when they match the task.\n\n"
        "UserSpace rules:\n"
        "- UserSpace/ stores structured personal markdown data such as expenses, "
        "tasks, memos, passwords, fitness, and coupons.\n"
        "- When creating a NEW UserSpace memory file, first read "
        "UserSpace/.formats.md for the classification guide and templates."
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
        f"── Available Skills ──\n{skill_index}\n\n"
        "Skill usage policy:\n"
        "- Skills are specialized operating instructions, not decorations.\n"
        "- If an available skill matches the user's task, load it with "
        "load_skill before doing substantial work.\n"
        "- Use skills proactively for code review, domain-specific workflows, "
        "debugging playbooks, document formats, external integrations, or any "
        "task where the skill description indicates relevant procedure.\n"
        "- Do not load unrelated skills just because they exist."
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
        return (
            "── Available Sub-Agents ──\n"
            "  (none)\n\n"
            "Sub-agent usage policy:\n"
            "- No sub-agents are currently available."
        )

    lines = ["── Available Sub-Agents ──"]
    for name, desc in agents.items():
        lines.append(f"  - {name}: {desc or '(no description)'}")
    lines.extend([
        "",
        "Sub-agent usage policy:",
        "- Sub-agents are isolated workers for focused subtasks. Use them "
        "proactively when their description matches the task.",
        "- Good delegation cases: unfamiliar code exploration, code review, "
        "large search tasks, risky investigation, parallelizable research, or "
        "work that would otherwise pollute the main conversation context.",
        "- Give each sub-agent a narrow prompt with clear scope, expected "
        "output, constraints, and relevant files or clues.",
        "- Prefer an exploration sub-agent before broad repository changes when "
        "the implementation area is unclear.",
        "- Prefer a review sub-agent before finalizing non-trivial code changes "
        "when a code-review agent is available.",
        "- Do not delegate trivial one-file reads, simple commands, or tasks "
        "that require immediate user interaction.",
        "- Use spawn_subagent(agent_name, prompt) to delegate.",
    ])
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
