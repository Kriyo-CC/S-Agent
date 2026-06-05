"""MCP client: connect to Model Context Protocol servers via stdio.

Dynamically discovers tools from external MCP servers and registers them
into the tool registry with namespaced names (mcp__<server>__<tool>).
"""

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from cli.render import console

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Lazy imports for optional MCP dependency
MCP_AVAILABLE = False
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    pass


class MCPClient:
    """Manages connections to MCP servers and their tools."""

    def __init__(self) -> None:
        self._sessions: Dict[str, "ClientSession"] = {}
        self._tool_map: Dict[str, Tuple[str, str]] = {}  # prefixed → (server, original)
        self._exit_stack = AsyncExitStack()

    @property
    def configured(self) -> bool:
        return MCP_AVAILABLE and _CONFIG_PATH.exists()

    def _load_config(self) -> List[dict]:
        if not self.configured:
            return []
        try:
            config = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            console.print(f"[red]  [MCP] Failed to parse config: {e}[/red]")
            return []
        return config.get("servers") or []

    async def connect(self) -> List[dict]:
        """Connect to all configured MCP servers and return discovered tool schemas."""
        if not MCP_AVAILABLE:
            console.print(
                "[yellow]Warning: 'mcp' package not found. Run: pip install mcp[/yellow]"
            )
            return []

        servers = self._load_config()
        if not servers:
            return []

        discovered = []
        for srv_cfg in servers:
            server_name = srv_cfg.get("name", "unnamed")
            try:
                if srv_cfg.get("transport", "stdio") != "stdio":
                    console.print(
                        f"[yellow]  [MCP] {server_name}: unsupported transport[/yellow]"
                    )
                    continue

                params = StdioServerParameters(
                    command=srv_cfg["command"], args=srv_cfg.get("args", [])
                )
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()

                mcp_resp = await session.list_tools()
                tool_list = mcp_resp.tools

                self._sessions[server_name] = session
                console.print(
                    f"[dim]  [MCP] {server_name}: Connected ({len(tool_list)} tools)[/dim]"
                )

                for tool in tool_list:
                    prefixed = f"mcp__{server_name}__{tool.name}"
                    self._tool_map[prefixed] = (server_name, tool.name)
                    discovered.append({
                        "name": prefixed,
                        "description": f"[{server_name}] {tool.description or tool.name}",
                        "input_schema": tool.inputSchema
                        or {"type": "object", "properties": {}},
                    })
            except Exception as e:
                console.print(
                    f"[red]  [MCP] Failed to connect to '{server_name}': {e}[/red]"
                )

        return discovered

    async def execute(self, prefixed_name: str, arguments: dict) -> str:
        """Route a tool call to the appropriate MCP server and execute it."""
        if prefixed_name not in self._tool_map:
            return f"Error: MCP tool '{prefixed_name}' not found in registry."

        srv_name, original_name = self._tool_map[prefixed_name]
        session = self._sessions.get(srv_name)
        if not session:
            return f"Error: MCP session for '{srv_name}' is inactive."

        try:
            result = await session.call_tool(original_name, arguments)
            parts = [
                item.text
                for item in (result.content or [])
                if hasattr(item, "text")
            ]
            return "\n".join(parts)[:50000] or "(no output)"
        except Exception as e:
            return f"Error during MCP execution: {e}"

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._tool_map

    async def close(self) -> None:
        """Gracefully close all MCP sessions."""
        try:
            await self._exit_stack.aclose()
        except Exception:
            pass
