"""Core agent loop: streaming + tool dispatch with event emission.

This is the heart of the agent — the Thinking-Acting cycle that calls the LLM,
streams text to the terminal, executes tools, feeds results back, and repeats
until the model produces a final answer.
"""

import os
from typing import List, Dict, Any, Optional, Callable

from config.settings import check_permission, load_rules
from agent.events import EventBus
from agent.types import AgentContext
from agent.accounting import SessionAccounting
from cli.render import console
from tools.registry import ToolRegistry


def _extract_input_summary(tool_input: dict, tool_name: str) -> str:
    """Extract a meaningful value from tool_input for display or permission checks.

    Prefers the most semantically important key (command, pattern, path, etc.)
    rather than relying on dict iteration order which may surface flags/booleans.
    Falls back to tool_name if input is empty.
    """
    if not tool_input:
        return tool_name
    for key in ("command", "pattern", "path", "prompt", "content"):
        if key in tool_input:
            return str(tool_input[key])
    return str(next(iter(tool_input.values())))


async def dispatch_tools(
    response_content: list,
    registry: ToolRegistry,
    bus: Optional[EventBus] = None,
    use_permissions: bool = True,
    mcp_executor: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Process tool_use blocks from the model's response.

    Args:
        response_content: Content blocks from the API response.
        registry: ToolRegistry containing handler functions.
        bus: Optional EventBus for pre/post_tool_use events.
        use_permissions: Whether to check permission rules.
        mcp_executor: Optional async callable for MCP tool invocation.
    Returns:
        List of tool_result dicts to append to message history.
    """
    results = []
    rules = load_rules() if use_permissions else None

    for block in response_content:
        if block.type != "tool_use":
            continue

        tool_name = block.name
        tool_input = block.input
        tool_use_id = block.id

        # ── Pre-tool event & permission check ────────────
        first_val = _extract_input_summary(tool_input, tool_name)[:80]

        if bus:
            pre_results = bus.emit(
                "pre_tool_use", tool=tool_name, input=tool_input
            )
            is_blocked = any(
                r.get("block") for r in pre_results if isinstance(r, dict)
            )
            if is_blocked:
                output = "Error: Execution blocked by system hook."
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": output,
                })
                continue

        if use_permissions:
            check_str = _extract_input_summary(tool_input, tool_name)
            allowed, reason = check_permission(tool_name, check_str, rules)
            if not allowed:
                console.print(f"[red][DENIED] {reason}[/red]")
                output = (
                    f"Blocked by Permission Policy: {check_str[:80]} "
                    f"(Reason: {reason})"
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": output,
                })
                continue

        console.print(f"[yellow]{tool_name}[/yellow] {first_val}...")

        # ── Execute tool ─────────────────────────────────
        # MCP tools need async execution
        if mcp_executor and tool_name.startswith("mcp__"):
            try:
                output = await mcp_executor(tool_name, tool_input)
            except Exception as e:
                output = f"Error during MCP execution: {e}"
        else:
            handler = registry.dispatch(tool_name)
            if handler:
                try:
                    output = handler(tool_input)
                except Exception as e:
                    output = f"Error during tool execution: {e}"
            else:
                output = f"Error: Unknown tool '{tool_name}'"

        console.print(output[:300])

        if bus:
            bus.emit(
                "post_tool_use",
                tool=tool_name,
                input=tool_input,
                output=str(output)[:1000],
            )

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(output),
        })

    return results


async def stream_loop(
    messages: List[Dict[str, Any]],
    registry: ToolRegistry,
    system: Optional[str] = None,
    ctx: Optional[AgentContext] = None,
    model: Optional[str] = None,
    bus: Optional[EventBus] = None,
    use_permissions: bool = True,
    mcp_executor: Optional[Callable] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
    accounting: Optional[SessionAccounting] = None,
) -> Any:
    """Main agent loop: stream + dispatch until the model finishes.

    Args:
        messages: The rolling conversation history (modified in-place).
        registry: ToolRegistry with schemas and handlers.
        system: System prompt.
        ctx: Optional AgentContext for dependency injection.
        model: Model ID override (takes precedence over ctx.model).
        bus: Optional EventBus for lifecycle events.
        use_permissions: Whether to apply permission checks.
        mcp_executor: Optional async MCP tool executor.
        extra_kwargs: Extra parameters for the API call.

    Returns:
        The final API response Message object.
    """
    # Resolve client and model: explicit params > AgentContext > defaults
    _client = ctx.client if ctx else None
    model_id = model or (ctx.model if ctx else None) or "claude-sonnet-4-20250514"
    _bus = bus or (ctx.bus if ctx else None)
    _use_permissions = use_permissions
    _mcp_executor = mcp_executor or (ctx.mcp_executor if ctx else None)

    system = system or f"You are a coding agent at {os.getcwd()}. Use tools to solve tasks."
    extra_kwargs = extra_kwargs or {}

    while True:
        console.print("\n[cyan]> Thinking...[/cyan]")

        try:
            with _client.messages.stream(
                model=model_id,
                system=system,
                messages=messages,
                tools=registry.list_schemas(),
                max_tokens=8000,
                **extra_kwargs,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                response = stream.get_final_message()

                # Record token usage if accounting is active
                if accounting and response.usage:
                    accounting.record_turn(
                        input_tokens=response.usage.input_tokens or 0,
                        output_tokens=response.usage.output_tokens or 0,
                    )
        except Exception as e:
            console.print(f"\n[red][Error] API call failed: {e}[/red]")
            raise

        print()
        messages.append({"role": "assistant", "content": response.content})

        if _bus:
            text_content = "".join(
                block.text
                for block in response.content
                if hasattr(block, "text")
            )
            if text_content:
                _bus.emit("agent_response", text=text_content)

        if response.stop_reason != "tool_use":
            return response

        results = await dispatch_tools(
            response.content, registry, _bus, _use_permissions, _mcp_executor
        )
        messages.append({"role": "user", "content": results})
