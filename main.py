#!/usr/bin/env python3
"""Agent Scaffold — CLI entry point.

A production-stable agent scaffold with:
- Tool registry with all tools in the tools/ package
- Skills support (lazy-loaded SKILL.md files)
- MCP support (dynamic external tool discovery)
- Generic sub-agent tool
- Permission governance
- Session persistence & context compression
- EventBus hooks for stats, timing, and extensibility

Usage:
  python main.py                        # Start interactive REPL
  python main.py --task "list files"    # Run a single task (non-interactive)
"""

import os
import sys
import asyncio
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any

# ── Internal imports ────────────────────────────────────
from config.settings import client, MODEL, load_rules

from agent.events import EventBus
from agent.loop import stream_loop
from agent.context import maybe_compress
from agent.session import (
    create_session,
    save_session,
    load_session,
    list_sessions,
    print_sessions_table,
)

from tools.registry import ToolRegistry
from tools.bash import register_bash_tool
from tools.file_ops import register_file_tools
from tools.skill import register_skill_tools, discover_skills
from tools.subagent import register_subagent_tool

# ── MCP (optional) ──────────────────────────────────────
MCP_CLIENT = None
try:
    from mcp.client import MCPClient

    MCP_CLIENT = MCPClient()
except Exception:
    pass


# ── Default hooks ───────────────────────────────────────


def _hook_stats():
    """Create a stats-tracking hook closure (tool usage counts)."""
    counts = defaultdict(int)

    def hook(event: str, **payload):
        if event == "session_start":
            counts.clear()
        elif event == "post_tool_use":
            counts[payload.get("tool", "?")] += 1
        elif event == "session_end":
            if counts:
                print(
                    f"\033[90m  [stats] Tool Usage: {dict(counts)}\033[0m"
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
                    print(
                        f"\033[90m  [timer] Slow tool '{payload.get('tool')}' "
                        f"took {dur:.1f}s\033[0m"
                    )

    return hook


# ── Build system prompt ─────────────────────────────────


def build_system_prompt() -> str:
    """Construct the system prompt with dynamic skill index."""
    skills = discover_skills()
    skill_index = (
        "\n".join(f"  - {n}: {d}" for n, d in skills.items())
        or "  (none installed)"
    )

    return (
        f"You are a coding agent at {os.getcwd()}.\n"
        "You have access to local tools, MCP tools, and specialized Skills.\n"
        "- For complex/exploratory subtasks, use spawn_subagent to delegate.\n"
        "- For domain knowledge, call list_skills then load_skill(name).\n"
        "- MCP tools are prefixed mcp__<server>__<tool>.\n"
        "Always prefer structured file tools (read/write/grep/glob) over raw bash.\n\n"
        f"Available Skills:\n{skill_index}"
    )


# ── Async MCP initialization ────────────────────────────


async def init_mcp(registry: ToolRegistry) -> None:
    """Connect to MCP servers and register discovered tools."""
    if MCP_CLIENT is None or not MCP_CLIENT.configured:
        return

    print("\033[90m  [MCP] Connecting to servers...\033[0m")
    mcp_schemas = await MCP_CLIENT.connect()

    for schema in mcp_schemas:
        name = schema["name"]
        registry.register(
            name=name,
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=lambda inp, n=name: "(use async MCP executor)",
        )

    if mcp_schemas:
        print(
            f"\033[90m  [MCP] Registered {len(mcp_schemas)} remote tools\033[0m"
        )


# ── REPL command dispatch ───────────────────────────────


def handle_command(
    query: str, session: Dict[str, Any], registry: ToolRegistry
) -> bool:
    """Handle special REPL commands. Returns True if query was a command."""
    if query == ":sessions":
        print_sessions_table()
        return True

    if query.startswith(":resume "):
        target = query[8:].strip()
        loaded = load_session(target)
        if loaded:
            session.update(loaded)
            mc = len(session.get("messages", []))
            print(
                f"  Resumed: \033[36m{session['id']}\033[0m "
                f"— '{session['title']}' ({mc} msgs)"
            )
        else:
            print(f"  Error: Session '{target}' not found.")
        return True

    if query.startswith(":fork "):
        src_id = query[6:].strip()
        src = load_session(src_id)
        if src:
            session["id"] = f"fork-{src['id'][:4]}"
            session["title"] = f"Fork of {src['title'][:30]}"
            session["messages"] = src.get("messages", [])
            session["created"] = datetime.now().isoformat()
            print(f"  Forked {src_id} → \033[36m{session['id']}\033[0m")
        else:
            print(f"  Error: Session '{src_id}' not found.")
        return True

    if query.startswith(":title "):
        session["title"] = query[7:].strip()
        print(f"  Title: '{session['title']}'")
        return True

    if query == ":save":
        save_session(session)
        print(f"  Saved: {session['id']}")
        return True

    if query == ":tools":
        print("  " + ", ".join(registry.list_names()))
        return True

    return False


# ── MCP async executor ──────────────────────────────────


async def _mcp_execute(name: str, args: dict) -> str:
    """Async wrapper called by dispatch_tools for MCP tools."""
    return await MCP_CLIENT.execute(name, args)


# ── Main ────────────────────────────────────────────────


async def main_async() -> None:
    # ── Setup EventBus + hooks ──────────────────────────
    bus = EventBus()
    stats = _hook_stats()
    bus.on("session_start", stats)
    bus.on("post_tool_use", stats)
    bus.on("session_end", stats)

    timer = _hook_timer()
    bus.on("pre_tool_use", timer)
    bus.on("post_tool_use", timer)

    # ── Build ToolRegistry ──────────────────────────────
    registry = ToolRegistry()
    register_bash_tool(registry)
    register_file_tools(registry)
    register_skill_tools(registry)

    # MCP tools (async init)
    await init_mcp(registry)

    # Subagent tool (needs full registry for recursive use)
    register_subagent_tool(registry, registry.list_schemas(), registry._handlers)

    # ── Build system prompt ─────────────────────────────
    system = build_system_prompt()

    # ── CLI startup ─────────────────────────────────────
    print(
        "\033[90m"
        f"Agent Scaffold v0.1.0 | model={MODEL} | "
        f"tools={len(registry)} | skills={len(discover_skills())}"
        "\033[0m"
    )
    print(
        "\033[90m"
        "Commands: q/exit, :sessions, :resume <id>, :fork <id>, "
        ":title <text>, :save, :tools"
        "\033[0m\n"
    )

    # ── Session init ────────────────────────────────────
    session = create_session()
    print(f"Session: \033[36m{session['id']}\033[0m\n")

    bus.emit("session_start")

    mcp_exec = _mcp_execute if MCP_CLIENT and MCP_CLIENT.configured else None

    try:
        # ── Main REPL ───────────────────────────────────
        while True:
            try:
                query = input(
                    f"\033[36magent ({session['id']}) >> \033[0m"
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Exiting...")
                break

            if not query:
                continue

            if query.lower() in ("q", "exit", "quit"):
                break

            if handle_command(query, session, registry):
                continue

            # Auto-title on first message
            if not session["messages"]:
                session["title"] = query[:50]

            # Append user message and run agent loop
            session["messages"].append({"role": "user", "content": query})
            stream_loop(
                messages=session["messages"],
                registry=registry,
                system=system,
                bus=bus,
                use_permissions=True,
                mcp_executor=mcp_exec,
            )

            # Post-turn maintenance
            maybe_compress(session["messages"])
            save_session(session)
            print()

    finally:
        # ── Shutdown ─────────────────────────────────────
        bus.emit("session_end")
        save_session(session)
        if MCP_CLIENT:
            await MCP_CLIENT.close()
        print(f"\033[90m  Session {session['id']} saved. Bye.\033[0m")


def main():
    """Entry point — starts the async event loop."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n  Interrupted. Goodbye.")


if __name__ == "__main__":
    main()
