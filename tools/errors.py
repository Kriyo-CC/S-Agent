"""Tool error hierarchy for structured error handling in concurrent dispatch.

Each error type maps to a specific failure mode. The concurrent dispatcher uses
these to decide how to handle failures: some are fail-isolated (one tool's error
does not affect siblings), while others (cancellation) must propagate globally.

Philosophy (from spec §7): Tools never throw — they always return strings.
These exceptions are for the dispatch infrastructure, not for tool handlers.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for all infrastructure-level tool errors.

    Not raised by tool handlers themselves — they return error strings.
    Raised by the dispatch layer when a tool cannot be executed at all.
    """


class ToolTimeoutError(ToolError):
    """A single tool exceeded its time budget.

    The tool's internal operation may still be running (especially for
    subprocess-based tools), but the dispatcher has stopped waiting.
    Other concurrently executing tools are unaffected.
    """


class ToolExecutionError(ToolError):
    """A tool's handler raised an unexpected exception.

    Wraps the original exception for logging/diagnostics. The concurrent
    dispatcher converts this to an error string in the tool_result so the
    model can see what happened and potentially recover.
    """

    def __init__(self, tool_name: str, original: Exception) -> None:
        self.tool_name = tool_name
        self.original = original
        super().__init__(f"Tool '{tool_name}' raised {type(original).__name__}: {original}")


class ToolNotFoundError(ToolError):
    """The requested tool name is not registered."""


class ToolPermissionDeniedError(ToolError):
    """Permission policy rejected this tool invocation."""


class ToolBlockedError(ToolError):
    """A system hook (EventBus pre_tool_use) blocked this tool invocation."""


class ToolInputValidationError(ToolError):
    """Tool input failed structural validation (wrong type, missing required fields)."""


# ── Error classification helpers ──────────────────────────


def is_transient(error: Exception) -> bool:
    """Check if an error might succeed on retry.

    Used for MCP/network tools where a connection may be temporarily unavailable.
    """
    transient_types = (TimeoutError, ConnectionError, OSError)
    if isinstance(error, ToolTimeoutError):
        return True
    if isinstance(error, ToolExecutionError):
        return isinstance(error.original, transient_types)
    return isinstance(error, transient_types)


def error_to_result(
    tool_use_id: str, error: Exception, *, include_traceback: bool = False
) -> dict:
    """Convert any exception to a tool_result content dict.

    This is the single place where infrastructure errors become tool_result
    strings, ensuring consistent formatting across all error paths.

    Args:
        tool_use_id: The tool_use block ID from the API response.
        error: The exception to convert.
        include_traceback: If True, append traceback for debugging.

    Returns:
        A tool_result dict suitable for appending to message history.
    """
    if isinstance(error, ToolTimeoutError):
        msg = f"Error: Tool timed out — {error}"
    elif isinstance(error, ToolPermissionDeniedError):
        msg = f"Blocked by Permission Policy: {error}"
    elif isinstance(error, ToolBlockedError):
        msg = f"Error: Execution blocked by system hook — {error}"
    elif isinstance(error, ToolNotFoundError):
        msg = f"Error: Unknown tool — {error}"
    elif isinstance(error, ToolInputValidationError):
        msg = f"Error: Invalid input — {error}"
    elif isinstance(error, ToolExecutionError):
        msg = f"Error during '{error.tool_name}' execution: {error.original}"
    else:
        msg = f"Error: {error}"

    if include_traceback:
        import traceback
        msg += f"\n{traceback.format_exc()}"

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": msg,
    }
