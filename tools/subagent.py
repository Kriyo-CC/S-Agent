"""Subagent tool: spawn isolated agents for delegated subtasks.

The subagent runs in a fresh conversation context, preventing its internal
trial-and-error from polluting the parent agent's context window. Only the
final textual result is returned.
"""

import os
from typing import List, Dict, Any

from config.settings import client, MODEL


def run_subagent(
    prompt: str,
    tools_schemas: List[Dict[str, Any]],
    tools_dispatch: Dict[str, Any],
    model: str = None,
) -> str:
    """Spawn an isolated agent loop for a subtask.

    Args:
        prompt: Detailed instructions for the subagent.
        tools_schemas: Tool definitions available to the subagent.
        tools_dispatch: Handler map for tool execution.
        model: Optional model override (defaults to global MODEL).

    Returns:
        Final text result from the subagent.
    """
    model_id = model or MODEL

    print(f"\033[35m  [subagent] spawned for: {prompt[:80]}...\033[0m")

    sub_messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

    system = (
        f"You are a subagent working on a specific subtask at {os.getcwd()}. "
        "Complete your task thoroughly. Summarize your result clearly at the end. "
        "Do NOT ask follow-up questions — just do the work and report back."
    )

    while True:
        response = client.messages.create(
            model=model_id,
            system=system,
            messages=sub_messages,
            tools=tools_schemas,
            max_tokens=8000,
        )
        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        results: List[Dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            handler = tools_dispatch.get(tool_name)
            first_val = str(list(block.input.values())[0])[:60] if block.input else ""
            print(f"\033[35m  [sub][{tool_name}] {first_val}...\033[0m")

            if handler:
                try:
                    output = handler(block.input)
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

    final = "".join(
        block.text
        for block in sub_messages[-1]["content"]
        if hasattr(block, "text")
    )

    print(f"\033[35m  [subagent] done: {final[:100]}...\033[0m")
    return final


def register_subagent_tool(registry, tools_schemas, tools_dispatch) -> None:
    """Register the spawn_subagent tool, capturing current tools_schemas/dispatch."""

    def handler(inp):
        return run_subagent(inp["prompt"], tools_schemas, tools_dispatch)

    registry.register(
        name="spawn_subagent",
        description=(
            "Spawn a fresh subagent to handle a subtask in an isolated context. "
            "Use for exploration, risky operations, or tasks that shouldn't "
            "pollute the main conversation history."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed instructions for the subagent.",
                }
            },
            "required": ["prompt"],
        },
        handler=handler,
    )
