"""Tool registry: unified management of tool schemas and dispatch handlers."""

from typing import Dict, List, Callable, Any, Optional


class ToolRegistry:
    """Central registry for agent tools.

    Each tool has:
    - a name (unique identifier)
    - a schema (JSON Schema for the Anthropic API)
    - a handler (callable that implements the tool)
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
    ) -> None:
        """Add a tool to the registry."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._handlers[name] = handler

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        return self._handlers.get(name)

    def get_handlers(self) -> Dict[str, Callable]:
        """Return a copy of all handler mappings."""
        return dict(self._handlers)

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return all tool schemas as a list for the Anthropic API."""
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def dispatch(self, name: str) -> Optional[Callable]:
        """Look up handler by name (alias for get_handler)."""
        return self._handlers.get(name)

    def merge(self, other: "ToolRegistry") -> None:
        """Absorb all tools from another registry."""
        self._tools.update(other._tools)
        self._handlers.update(other._handlers)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
