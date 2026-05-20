"""Tool registry: unified management of tool schemas and dispatch handlers.

Each tool has:
- a name (unique identifier)
- a schema (JSON Schema for the Anthropic API)
- a handler (callable that implements the tool)
- optional metadata (timeout override, resource tags, etc.)
"""

from __future__ import annotations

from typing import Dict, List, Callable, Any, Optional


class ToolRegistry:
    """Central registry for agent tools.

    Tools are registered with a name, description, input_schema, and handler.
    Optional metadata can carry per-tool configuration like custom timeouts
    or resource tags for conflict detection.

    Thread-safe for reads; writes should happen during bootstrap only.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._handlers: Dict[str, Callable] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a tool to the registry.

        Args:
            name: Unique tool identifier.
            description: Human-readable description for the model.
            input_schema: JSON Schema for the tool's input parameters.
            handler: Callable that executes the tool. May be sync (returns str)
                     or async (returns Awaitable[str]).
            metadata: Optional dict with per-tool configuration.
                      Supported keys:
                      - timeout: float — per-tool timeout override (seconds)
                      - writes_files: bool — tool modifies filesystem paths
                      - resource_key: str — input key that identifies the
                        resource being modified (e.g. "path" for write/edit)
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._handlers[name] = handler
        if metadata:
            self._metadata[name] = metadata

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        return self._handlers.get(name)

    def get_metadata(self, name: str) -> Dict[str, Any]:
        """Return per-tool metadata dict (empty if not configured)."""
        return self._metadata.get(name, {})

    def get_timeout(self, name: str, default: float = 300.0) -> float:
        """Return the per-tool timeout override, or the default."""
        meta = self._metadata.get(name, {})
        return meta.get("timeout", default)

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
        """Absorb all tools, handlers, and metadata from another registry."""
        self._tools.update(other._tools)
        self._handlers.update(other._handlers)
        self._metadata.update(other._metadata)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def reset(self) -> None:
        """Remove all registered tools, handlers, and metadata.

        Useful in tests to start fresh without creating a new instance.
        """
        self._tools.clear()
        self._handlers.clear()
        self._metadata.clear()
