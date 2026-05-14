"""Event bus: Pub/Sub lifecycle hooks for the agent.

Events fired:
- session_start: agent loop begins
- pre_tool_use: before a tool executes (can intercept via {"block": True})
- post_tool_use: after a tool completes
- tool_error: tool execution fails (reserved, not yet emitted)
- agent_response: LLM finishes a text turn (reserved, not yet consumed)
- session_end: agent loop terminates
"""

from collections import defaultdict
from typing import Dict, List, Callable, Any

from cli.render import console


class EventBus:
    """A simple Pub/Sub event system to manage agent lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable[..., Any]) -> "EventBus":
        """Register a callback for an event. Returns self for chaining."""
        self._handlers[event].append(handler)
        return self

    def emit(self, event: str, **payload: Any) -> List[Any]:
        """Trigger an event, calling all registered handlers with **payload."""
        results = []
        for handler in self._handlers[event]:
            try:
                result = handler(event=event, **payload)
                if result is not None:
                    results.append(result)
            except Exception as e:
                console.print(f"[red][EventBus] Hook error on '{event}': {e}[/red]")
        return results

    def remove(self, event: str, handler: Callable) -> None:
        """Remove a specific handler from an event."""
        if event in self._handlers and handler in self._handlers[event]:
            self._handlers[event].remove(handler)
