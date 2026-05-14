"""Subagent tool: spawn isolated agents from folder-based definitions.

Agent definitions live in agents/<name>/agent.yaml with:
  - name, description, model
  - allowed_tools: subset of tools available to the subagent
  - system: system prompt for the subagent

The subagent runs in a fresh conversation context, preventing its internal
trial-and-error from polluting the parent agent's context window. Only the
final textual result is returned.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml

from config.settings import check_permission, load_rules, create_client, get_default_model
from agent.types import AgentContext
from cli.render import console
from tools.registry import ToolRegistry

AGENTS_DIR = Path("agents")


def discover_agents() -> Dict[str, str]:
    """Scan agents/ directory, return {name: description} for non-main agents."""
    agents: Dict[str, str] = {}
    if not AGENTS_DIR.exists():
        return agents
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and data.get("name") and data["name"] != "main":
                agents[data["name"]] = data.get("description", "")
        except Exception:
            continue
    return agents


def load_agent_def(agent_name: str) -> Optional[dict]:
    """Load and return an agent definition from agents/<name>/agent.yaml.

    Returns None if the agent directory or YAML file does not exist.
    """
    yaml_path = AGENTS_DIR / agent_name / "agent.yaml"
    if not yaml_path.exists():
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]Error loading agent '{agent_name}': {e}[/red]")
        return None


def build_filtered_registry(
    agent_def: dict, full_registry: ToolRegistry
) -> ToolRegistry:
    """Build a sub-registry containing only the tools allowed by the agent definition.

    Args:
        agent_def: Parsed agent.yaml dict with allowed_tools list.
        full_registry: The parent's full ToolRegistry.

    Returns:
        A new ToolRegistry with only the allowed tools.
    """
    allowed = set(agent_def.get("allowed_tools", []))
    sub_registry = ToolRegistry()

    for name in sorted(allowed):
        schema = full_registry.get_schema(name)
        handler = full_registry.get_handler(name)
        if schema and handler:
            sub_registry.register(
                name=name,
                description=schema["description"],
                input_schema=schema["input_schema"],
                handler=handler,
            )

    return sub_registry


def run_subagent(
    agent_name: str,
    prompt: str,
    full_registry: ToolRegistry,
    ctx: Optional[AgentContext] = None,
    model: Optional[str] = None,
) -> str:
    """Spawn an isolated subagent from an agent definition.

    Args:
        agent_name: Name of the agent definition in agents/<name>/agent.yaml.
        prompt: Detailed instructions for the subagent.
        full_registry: The parent's ToolRegistry (filtered for the subagent).
        ctx: Optional AgentContext with client, model, etc.
        model: Optional model override.

    Returns:
        Final text result from the subagent.
    """
    # ── Load agent definition ────────────────────────────────
    agent_def = load_agent_def(agent_name)
    if agent_def is None:
        return f"Error: agent '{agent_name}' not found in agents/ directory."

    # ── Build filtered registry ──────────────────────────────
    sub_registry = build_filtered_registry(agent_def, full_registry)
    if len(sub_registry) == 0:
        return f"Error: agent '{agent_name}' has no valid tools configured."

    # ── Resolve client and model ─────────────────────────────
    _client = ctx.client if ctx else create_client()
    sub_model = (
        model
        or agent_def.get("model")
        or (ctx.model if ctx else None)
        or get_default_model()
    )

    sub_system = agent_def.get("system") or (
        f"You are a subagent ({agent_name}) at {os.getcwd()}. "
        "Complete your task thoroughly."
    )

    rules = load_rules()

    console.print(
        f"[magenta]  [subagent:{agent_name}] spawned: {prompt[:80]}...[/magenta]"
    )

    # ── Subagent loop ────────────────────────────────────────
    sub_messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

    while True:
        try:
            response = _client.messages.create(
                model=sub_model,
                system=sub_system,
                messages=sub_messages,
                tools=sub_registry.list_schemas(),
                max_tokens=8000,
            )
        except Exception as e:
            console.print(f"[red]  [subagent] API error: {e}[/red]")
            return f"Subagent error: {e}"

        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        # ── Execute tools ────────────────────────────────────
        results: List[Dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            handler = sub_registry.dispatch(tool_name)
            first_val = (
                str(list(tool_input.values())[0])[:60] if tool_input else ""
            )
            console.print(
                f"[magenta]  [sub:{agent_name}][{tool_name}] {first_val}...[/magenta]"
            )

            if handler:
                check_str = (
                    str(list(tool_input.values())[0]) if tool_input else tool_name
                )
                allowed, reason = check_permission(tool_name, check_str, rules)
                if not allowed:
                    console.print(f"[red][DENIED] {reason}[/red]")
                    output = (
                        f"Blocked by Permission Policy: {check_str[:80]} "
                        f"(Reason: {reason})"
                    )
                else:
                    try:
                        output = handler(tool_input)
                    except Exception as e:
                        output = f"Error: {e}"
            else:
                output = f"Error: Unknown tool '{tool_name}'"

            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output),
            })

        sub_messages.append({"role": "user", "content": results})

    # ── Extract final text ───────────────────────────────────
    final = "".join(
        block.text
        for block in sub_messages[-1]["content"]
        if hasattr(block, "text")
    )

    console.print(
        f"[magenta]  [subagent:{agent_name}] done: {final[:100]}...[/magenta]"
    )
    return final


def register_subagent_tool(registry: ToolRegistry) -> None:
    """Register the spawn_subagent tool using the full registry.

    The subagent receives the full registry and filters it at runtime
    based on the agent definition's allowed_tools.
    """

    def handler(inp: dict) -> str:
        agent_name = inp.get("agent_name", "main")
        prompt = inp.get("prompt", "")
        return run_subagent(agent_name, prompt, registry)

    registry.register(
        name="spawn_subagent",
        description=(
            "Spawn a subagent for a delegated subtask. The subagent runs in an "
            "isolated conversation context, preventing internal trial-and-error "
            "from polluting your context. Provide an agent_name to select which "
            "agent definition to use (use list_agents to see available options)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": (
                        "Agent definition to use (from agents/ directory). "
                        "Defaults to 'main'."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instructions for the subagent.",
                },
            },
            "required": ["prompt"],
        },
        handler=handler,
    )
