"""Core agent loop: streaming + concurrent tool dispatch with event emission.

This is the heart of the agent — the Thinking-Acting cycle that calls the LLM,
streams text to the terminal, executes tools concurrently, feeds results back,
and repeats until the model produces a final answer.

Concurrency model (enterprise-grade):
- Independent tool_use blocks from a single model response execute concurrently
  via asyncio.gather(return_exceptions=True).
- One tool's failure never cancels sibling tools (error isolation).
- User cancellation (Ctrl+C) propagates CancelledError to cancel all in-flight tools.
- Sync tool handlers run in the default thread pool (asyncio.to_thread) to avoid
  blocking the event loop.
- Per-tool timeout via asyncio.wait_for prevents hung tools from stalling the agent.
"""

import asyncio
import os
from typing import List, Dict, Any, Optional, Callable

from config.settings import check_permission, load_rules
from agent.events import EventBus
from agent.types import AgentContext
from agent.accounting import SessionAccounting
from cli.render import console
from tools.registry import ToolRegistry
from tools.errors import (
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolBlockedError,
    ToolInputValidationError,
    ToolPermissionDeniedError,
    ToolTimeoutError,
    error_to_result,
)

# ── Default per-tool timeout (generous safety net; internal tool
#    timeouts like bash's 120s subprocess timeout fire first) ────
DEFAULT_TOOL_TIMEOUT = 300.0  # seconds

_CACHE_READ_FIELDS = (
    "cache_read_input_tokens",
    "input_cache_hit_tokens",
    "cache_hit_input_tokens",
    "prompt_cache_hit_tokens",
)
_CACHE_MISS_FIELDS = (
    "cache_creation_input_tokens",
    "input_cache_miss_tokens",
    "cache_miss_input_tokens",
    "prompt_cache_miss_tokens",
)


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


def _usage_int(usage: Any, names: tuple[str, ...]) -> int:
    """Return the first available integer usage field from an SDK object."""
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return 0


def _extract_billable_usage(usage: Any) -> tuple[int, int, int]:
    """Extract cache-aware billable token counts from a response usage object.

    Returns:
        (cache_miss_input_tokens, cache_hit_input_tokens, output_tokens)

    Anthropic-compatible usage exposes `input_tokens`, `output_tokens`,
    `cache_creation_input_tokens`, and `cache_read_input_tokens`. DeepSeek
    compatible gateways may use cache_hit/cache_miss aliases, so those are
    checked as well.
    """
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cache_hit_tokens = _usage_int(usage, _CACHE_READ_FIELDS)
    cache_miss_extra_tokens = _usage_int(usage, _CACHE_MISS_FIELDS)
    return (input_tokens + cache_miss_extra_tokens, cache_hit_tokens, output_tokens)


def _classify_tool_block(
    block,
    registry: ToolRegistry,
    bus: Optional[EventBus],
    rules: Optional[list],
    use_permissions: bool,
    mcp_executor: Optional[Callable],
) -> tuple:
    """Pre-flight checks for a single tool_use block.

    Determines whether a block should be executed, and if not, why not.
    This runs synchronously before any tool execution starts so that
    permission denials and hook blocks are surfaced immediately.

    Returns:
        (status, error_message, handler) where status is one of:
        'executable', 'blocked', 'denied', 'unknown', 'invalid_input'
    """
    tool_name = block.name
    tool_input = block.input if isinstance(block.input, dict) else {}

    # ── Input type validation ──
    if not isinstance(block.input, dict) and block.input is not None:
        return (
            "invalid_input",
            ToolInputValidationError(
                f"Invalid input type for '{tool_name}': "
                f"expected dict, got {type(block.input).__name__}"
            ),
            None,
        )

    # ── System hook check (pre_tool_use event) ──
    if bus:
        pre_results = bus.emit("pre_tool_use", tool=tool_name, input=tool_input)
        is_blocked = any(
            r.get("block") for r in pre_results if isinstance(r, dict)
        )
        if is_blocked:
            return (
                "blocked",
                ToolBlockedError(
                    f"Tool '{tool_name}' execution blocked by system hook"
                ),
                None,
            )

    # ── Permission check ──
    if use_permissions:
        check_str = _extract_input_summary(tool_input, tool_name)
        allowed, reason = check_permission(tool_name, check_str, rules)
        if not allowed:
            console.print(f"[red][DENIED] {reason}[/red]")
            return (
                "denied",
                ToolPermissionDeniedError(
                    f"{check_str[:80]} (Reason: {reason})"
                ),
                None,
            )

    # ── Handler lookup ──
    handler = registry.dispatch(tool_name)
    is_mcp = mcp_executor and tool_name.startswith("mcp__")
    if handler is None and not is_mcp:
        return (
            "unknown",
            ToolNotFoundError(f"Unknown tool '{tool_name}'"),
            None,
        )

    return ("executable", None, handler)


def _detect_write_conflicts(tool_specs: list) -> set:
    """Detect concurrent modifications to the same file path.

    When multiple write/edit/revert tools target the same file, concurrent
    execution produces unpredictable results (last-write-wins). This function
    identifies conflicting groups so the dispatcher can serialize them.

    Args:
        tool_specs: List of (original_index, block, handler, status, error_msg) tuples
                    where status == 'executable'.

    Returns:
        Set of file paths that have conflicts (2+ tools targeting them).
    """
    write_tools = {"write", "edit", "revert"}
    path_counts: Dict[str, int] = {}

    for _idx, block, _handler, _status, _error_msg in tool_specs:
        if block.name not in write_tools:
            continue
        tool_input = block.input if isinstance(block.input, dict) else {}
        target_path = tool_input.get("path", "")
        if target_path:
            path_counts[target_path] = path_counts.get(target_path, 0) + 1

    return {path for path, count in path_counts.items() if count > 1}


async def _execute_single_tool(
    tool_name: str,
    tool_input: dict,
    tool_use_id: str,
    handler: Optional[Callable],
    *,
    mcp_executor: Optional[Callable] = None,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
    bus: Optional[EventBus] = None,
) -> Dict[str, Any]:
    """Execute one tool with comprehensive error handling.

    This is the atomic unit of concurrent execution. It handles all failure
    modes for a single tool invocation and always returns a tool_result dict
    (never raises Exception). The only exception that propagates is
    asyncio.CancelledError, which signals a user interrupt and must cancel
    all sibling tasks.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Input dict (already validated as a dict).
        tool_use_id: The tool_use block ID from the API response.
        handler: Callable from the registry (may be None for MCP tools).
        mcp_executor: Optional async callable for MCP tool execution.
        timeout: Per-tool timeout in seconds.
        bus: Optional EventBus for post_tool_use events.

    Returns:
        A tool_result dict with 'type', 'tool_use_id', and 'content' keys.
    """
    # ── Execute with structured error handling ──
    error: Optional[ToolError] = None
    output: str = ""

    try:
        if mcp_executor and tool_name.startswith("mcp__"):
            # MCP tools: native async
            output = await asyncio.wait_for(
                mcp_executor(tool_name, tool_input),
                timeout=timeout,
            )
        elif handler is not None:
            if asyncio.iscoroutinefunction(handler):
                # Async tool handler
                output = await asyncio.wait_for(
                    handler(tool_input),
                    timeout=timeout,
                )
            else:
                # Sync tool handler → run in default thread pool to
                # avoid blocking the event loop during I/O or subprocess calls
                output = await asyncio.wait_for(
                    asyncio.to_thread(handler, tool_input),
                    timeout=timeout,
                )
        else:
            error = ToolNotFoundError(
                f"No handler available for '{tool_name}'"
            )

    except asyncio.TimeoutError:
        error = ToolTimeoutError(
            f"Tool '{tool_name}' timed out after {timeout:.0f}s. "
            f"The underlying operation may still be running."
        )
    except asyncio.CancelledError:
        # Must propagate — gather uses this to cancel sibling tasks on Ctrl+C.
        # We still emit post_tool_use so the UI shows the tool was interrupted.
        if bus:
            try:
                bus.emit(
                    "post_tool_use",
                    tool=tool_name,
                    input=tool_input,
                    output=f"[CANCELLED] Tool '{tool_name}' was cancelled.",
                )
            except Exception:
                pass
        raise
    except Exception as exc:
        error = ToolExecutionError(tool_name, exc)

    # ── Convert structured error to result dict ──
    if error is not None:
        result = error_to_result(tool_use_id, error)
    else:
        result = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(output),
        }

    # ── Post-tool event (best-effort) ──
    if bus:
        try:
            bus.emit(
                "post_tool_use",
                tool=tool_name,
                input=tool_input,
                output=result["content"][:1000],
            )
        except Exception:
            pass  # Event errors must never affect tool results

    # ── Truncate and display ──
    console.print(result["content"][:300])

    return result


async def dispatch_tools(
    response_content: list,
    registry: ToolRegistry,
    bus: Optional[EventBus] = None,
    use_permissions: bool = True,
    mcp_executor: Optional[Callable] = None,
    tool_timeout: float = DEFAULT_TOOL_TIMEOUT,
) -> List[Dict[str, Any]]:
    """Process tool_use blocks from the model's response concurrently.

    Each independent tool_use block executes concurrently via asyncio.gather.
    Failures in one tool do not affect sibling tools (error isolation).
    Permission checks and hook blocks run synchronously before any tool
    executes, so the model never waits for a tool that will be denied.

    Error categories handled (in order of precedence):
    1. Input validation  — wrong type → immediate error result
    2. System hook block  — pre_tool_use returns {block: true} → immediate error
    3. Permission denied  — policy rejects → immediate error
    4. Unknown tool       — not in registry → immediate error
    5. Tool timeout       — asyncio.wait_for expires → error, siblings continue
    6. Tool crash         — handler raises Exception → error, siblings continue
    7. User cancellation  — CancelledError → propagates, all tools cancelled

    Resource conflict detection:
    When multiple write/edit/revert tools target the same file path, the
    dispatcher serializes those specific tools (within the concurrent batch)
    to prevent last-write-wins data loss. Non-conflicting tools still run
    concurrently.

    Args:
        response_content: Content blocks from the API response.
        registry: ToolRegistry containing handler functions.
        bus: Optional EventBus for pre/post_tool_use events.
        use_permissions: Whether to check permission rules.
        mcp_executor: Optional async callable for MCP tool invocation.
        tool_timeout: Per-tool timeout in seconds (default 300s).

    Returns:
        List of tool_result dicts in original tool_use block order,
        suitable for appending to message history.
    """
    rules = load_rules() if use_permissions else None

    # ── Phase 1: Classify all tool_use blocks ──────────────
    # Each block gets a status: executable, blocked, denied, unknown, invalid_input
    # Pre-computed error results avoid spawning tasks for doomed tools.

    specs: List[tuple] = []  # (original_index, block, handler, status, error_msg)

    for i, block in enumerate(response_content):
        if getattr(block, "type", None) != "tool_use":
            continue

        status, error_msg, handler = _classify_tool_block(
            block, registry, bus, rules, use_permissions, mcp_executor
        )

        if status == "executable":
            first_val = _extract_input_summary(
                block.input if isinstance(block.input, dict) else {}, block.name
            )[:80]
            console.print(f"[yellow]{block.name}[/yellow] {first_val}...")

        specs.append((i, block, handler, status, error_msg))

    if not specs:
        return []

    # ── Phase 2: Detect resource conflicts ─────────────────
    # Tools modifying the same file are serialized within groups to
    # prevent data races. Non-conflicting tools still run concurrently.

    conflicting_paths = _detect_write_conflicts(
        [(i, b, h, s, e) for i, b, h, s, e in specs if s == "executable"]
    )

    # ── Phase 3: Build concurrent execution plan ───────────
    # We build a list of coroutines, one per executable tool.
    # Error-isolated tools are gathered together; conflicting tools
    # are chained sequentially within each conflict group.

    # Map: original_index -> coroutine (or None for pre-computed errors)
    coro_map: Dict[int, Any] = {}
    # Track serialization chains: path -> list of (original_index, coroutine)
    serial_groups: Dict[str, list] = {p: [] for p in conflicting_paths}

    for i, block, handler, status, error_msg in specs:
        if status != "executable":
            continue

        tool_name = block.name
        tool_input = block.input if isinstance(block.input, dict) else {}
        # Per-tool timeout from registry metadata, falling back to the dispatch-level default
        per_tool_timeout = registry.get_timeout(tool_name, default=tool_timeout)

        async def make_coro(
            tn=tool_name,
            ti=tool_input,
            tid=block.id,
            h=handler,
            timeout=per_tool_timeout,
        ):
            return await _execute_single_tool(
                tool_name=tn,
                tool_input=ti,
                tool_use_id=tid,
                handler=h,
                mcp_executor=mcp_executor,
                timeout=timeout,
                bus=bus,
            )

        # Check if this tool is part of a conflict group
        target_path = tool_input.get("path", "") if isinstance(tool_input, dict) else ""
        if target_path in conflicting_paths and block.name in {"write", "edit", "revert"}:
            serial_groups[target_path].append((i, make_coro))
        else:
            coro_map[i] = make_coro

    # ── Phase 4: Replace conflicting coroutines with serialized chains ──
    for path, entries in serial_groups.items():
        if not entries:
            continue
        if len(entries) == 1:
            # Shouldn't happen (conflicting_paths filters for count > 1),
            # but handle gracefully
            idx, coro = entries[0]
            coro_map[idx] = coro
            continue

        console.print(
            f"[dim]  [concurrency] Serializing {len(entries)} tools "
            f"targeting '{path}' to prevent write conflicts[/dim]"
        )

        async def serial_chain(ents=entries):
            """Execute a chain of coroutines sequentially, returning all results."""
            results = []
            for _idx, coro_factory in ents:
                result = await coro_factory()
                results.append((_idx, result))
            return results

        # Replace individual coroutines with a single chained coroutine
        first_idx = entries[0][0]
        coro_map[first_idx] = serial_chain
        for idx, _ in entries[1:]:
            if idx in coro_map:
                del coro_map[idx]

    # ── Phase 5: Execute all coroutines concurrently ───────
    coro_entries = sorted(coro_map.items(), key=lambda x: x[0])

    try:
        raw_results = await asyncio.gather(
            *[c() for _, c in coro_entries],
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        # CancelledError from gather: one of the tasks was cancelled
        # (user interrupt). This propagates up to stream_loop which
        # should handle it or let it bubble to the REPL.
        raise
    except KeyboardInterrupt:
        # Belt-and-suspenders: KeyboardInterrupt during gather setup
        raise

    # ── Phase 6: Assemble final results (original order) ───
    # Flatten results from both serial chains and independent tasks,
    # maintaining original tool_use block ordering.

    # Build a flat map: original_index -> result_dict
    result_map: Dict[int, dict] = {}

    for (orig_idx, _), raw in zip(coro_entries, raw_results):
        if isinstance(raw, BaseException):
            # A BaseException that escaped _execute_single_tool
            # (typically CancelledError caught by return_exceptions=True)
            result_map[orig_idx] = {
                "type": "tool_result",
                "tool_use_id": specs[orig_idx][1].id,
                "content": f"Error: Tool execution interrupted: {raw}",
            }
        elif isinstance(raw, list):
            # Serial chain result: list of (idx, result) tuples
            for chain_idx, chain_result in raw:
                result_map[chain_idx] = chain_result
        else:
            # Normal result dict from _execute_single_tool
            result_map[orig_idx] = raw

    # Assemble in original order — pre-computed errors use error_to_result()
    # for consistent formatting with runtime errors from _execute_single_tool.
    final_results = []
    for i, block, handler, status, error_msg in specs:
        if status == "executable":
            if i in result_map:
                final_results.append(result_map[i])
            else:
                # Fallback: should not happen, but guard against it
                final_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Error: Tool result missing after dispatch.",
                })
        else:
            # Pre-computed error — error_msg is a ToolError instance
            final_results.append(error_to_result(block.id, error_msg))

    return final_results


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
    if _client is None:
        raise RuntimeError("stream_loop requires an AgentContext with an Anthropic client.")

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
                    input_tokens, cached_input_tokens, output_tokens = (
                        _extract_billable_usage(response.usage)
                    )
                    accounting.record_turn(
                        input_tokens=input_tokens,
                        cached_input_tokens=cached_input_tokens,
                        output_tokens=output_tokens,
                    )
        except asyncio.CancelledError:
            console.print("\n[yellow][Cancelled] User interrupted API call.[/yellow]")
            raise
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

        try:
            results = await dispatch_tools(
                response.content, registry, _bus, _use_permissions, _mcp_executor
            )
        except asyncio.CancelledError:
            console.print(
                "\n[yellow][Cancelled] Tool execution interrupted. "
                "Saving partial results...[/yellow]"
            )
            # Re-raise so the REPL can handle the cancellation
            raise

        messages.append({"role": "user", "content": results})
