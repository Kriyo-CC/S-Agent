"""Application bootstrap — assembles all layers and starts the REPL.

This is the single orchestration point:
1. Create Anthropic client and resolve model
2. Set up EventBus with stats/timer hooks
3. Build ToolRegistry with all tools
4. Connect MCP servers (optional)
5. Create AgentContext with all dependencies
6. Start the REPL loop
7. Clean shutdown on exit
"""

import asyncio
from collections import defaultdict
from datetime import datetime

from config.settings import create_client, get_default_model
from agent.events import EventBus
from agent.session import create_session
from agent.types import AgentContext
from cli.render import console
from cli.repl import run_repl
from tools.registry import ToolRegistry
from tools.bash import register_bash_tool
from tools.file_ops import register_file_tools
from tools.ledger import register_ledger_tools
from tools.skill import register_skill_tools, discover_skills
from tools.subagent import register_subagent_tool
from tools.web_search import register_web_search_tools
from tools.ask_user import register_ask_user_tool
from tools.memory_tools import register_memory_tools

# ── Optional MCP ────────────────────────────────────────
MCP_CLIENT = None
try:
    from mcp.client import MCPClient

    MCP_CLIENT = MCPClient()
except Exception:
    pass


# ── EventBus Hooks ──────────────────────────────────────


def _hook_stats():
    """Create a stats-tracking hook closure (tool usage counts)."""
    counts: defaultdict[str, int] = defaultdict(int)

    def hook(event: str, **payload):
        if event == "session_start":
            counts.clear()
        elif event == "post_tool_use":
            counts[payload.get("tool", "?")] += 1
        elif event == "session_end":
            if counts:
                console.print(
                    f"[dim]  [stats] Tool Usage: {dict(counts)}[/dim]"
                )

    return hook


def _hook_timer():
    """Create a timer hook (flags slow tools >5s)."""
    starts = {}

    def hook(event: str, **payload):
        if event == "pre_tool_use":
            starts[payload.get("tool")] = datetime.now()
        elif event == "post_tool_use":
            start = starts.pop(payload.get("tool"), None)
            if start:
                dur = (datetime.now() - start).total_seconds()
                if dur > 5.0:
                    console.print(
                        f"[dim]  [timer] Slow tool '{payload.get('tool')}' "
                        f"took {dur:.1f}s[/dim]"
                    )

    return hook


# ── MCP helpers ─────────────────────────────────────────


async def init_mcp(registry: ToolRegistry) -> None:
    """Connect to MCP servers and register discovered tools."""
    if MCP_CLIENT is None or not MCP_CLIENT.configured:
        return

    console.print("[dim]  [MCP] Connecting to servers...[/dim]")
    mcp_schemas = await MCP_CLIENT.connect()

    for schema in mcp_schemas:
        name = schema["name"]
        registry.register(
            name=name,
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=lambda *a, _n=name: "(use async MCP executor)",
        )

    if mcp_schemas:
        console.print(
            f"[dim]  [MCP] Registered {len(mcp_schemas)} remote tools[/dim]"
        )


async def _mcp_execute(name: str, args: dict) -> str:
    """Async wrapper called by dispatch_tools for MCP tools."""
    if MCP_CLIENT is None:
        return "Error: MCP not available"
    return await MCP_CLIENT.execute(name, args)


# ── Application ─────────────────────────────────────────


async def run_app() -> None:
    """Bootstrap all layers and run the REPL."""
    # ── Bootstrap client & model ────────────────────────
    anthropic_client = create_client()
    model_id = get_default_model()

    # ── Setup EventBus + hooks ─────────────────────────
    bus = EventBus()
    stats = _hook_stats()
    bus.on("session_start", stats)
    bus.on("post_tool_use", stats)
    bus.on("session_end", stats)

    timer = _hook_timer()
    bus.on("pre_tool_use", timer)
    bus.on("post_tool_use", timer)

    # ── Build ToolRegistry ─────────────────────────────
    registry = ToolRegistry()
    register_bash_tool(registry)
    register_file_tools(registry)
    register_ledger_tools(registry)
    register_skill_tools(registry)
    register_web_search_tools(registry)
    register_ask_user_tool(registry)
    register_memory_tools(registry)

    # MCP tools (async init)
    await init_mcp(registry)

    # Subagent tool (passes full registry, filters at runtime by agent def)
    register_subagent_tool(registry)

    # ── Create AgentContext ────────────────────────────
    mcp_exec = (
        _mcp_execute if MCP_CLIENT and MCP_CLIENT.configured else None
    )
    session = create_session()

    ctx = AgentContext(
        client=anthropic_client,
        model=model_id,
        bus=bus,
        session=session,
        mcp_executor=mcp_exec,
        use_permissions=True,
        console=console,
    )

    # ── Startup banner ─────────────────────────────────
    console.print(
        f"[dim]Agent Scaffold v0.1.0 | model={model_id} | "
        f"tools={len(registry)} | skills={len(discover_skills())}[/dim]"
    )
    console.print(
        "[dim]Commands: q/exit, :sessions, :resume <id>, :fork <id>, "
        ":title <text>, :save, :tools, :accounting[/dim]\n"
    )
    console.print(f"Session: [cyan]{session['id']}[/cyan]\n")

    # ── Run REPL ───────────────────────────────────────
    try:
        await run_repl(ctx, registry)
    finally:
        # ── Shutdown ───────────────────────────────────
        if MCP_CLIENT:
            await MCP_CLIENT.close()
        console.print(f"[dim]  Session {session['id']} saved. Bye.[/dim]")


def main() -> None:
    """Entry point called from main.py."""
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        console.print("\n  Interrupted. Goodbye.")
