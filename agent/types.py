"""Shared types for the agent engine layer.

AgentContext is the central dependency-injection container — it bundles
everything the loop, tools, and CLI need, making it possible to mock or
swap any component for testing.
"""

from dataclasses import dataclass
from typing import Optional, Callable, Any

from anthropic import Anthropic
from rich.console import Console


@dataclass
class AgentContext:
    """Bundled dependencies injected into agent loop and tools.

    Created once in cli/app.py, passed to stream_loop, dispatch_tools,
    and every tool that needs terminal output or config access.
    """

    client: Anthropic
    model: str
    bus: Any  # EventBus (lazy circular import)
    session: dict
    mcp_executor: Optional[Callable] = None
    use_permissions: bool = True
    console: Optional[Console] = None
