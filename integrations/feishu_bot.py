"""Feishu long-connection bot entry point.

This module connects a Feishu/Lark bot through the official lark-oapi
WebSocket long-connection channel and routes inbound messages through the
existing S-Agent runtime.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dotenv import load_dotenv

from agent.accounting import SessionAccounting
from agent.events import EventBus
from agent.loop import stream_loop
from agent.prompt import build_system_prompt
from agent.session import create_session, save_session
from agent.types import AgentContext
from cli.app import MCP_CLIENT, _hook_stats, _hook_timer, _mcp_execute, init_mcp
from cli.render import console
from config.settings import create_client, get_default_model
from tools.ask_user import register_ask_user_tool
from tools.bash import register_bash_tool
from tools.file_ops import register_file_tools
from tools.ledger import register_ledger_tools
from tools.memory_tools import register_memory_tools
from tools.registry import ToolRegistry
from tools.skill import discover_skills, register_skill_tools
from tools.subagent import register_subagent_tool
from tools.web_search import register_web_search_tools


def _env(name: str, fallback: str | None = None) -> str | None:
    """Read a value from FEISHU_* first, then compatible LARK_* names."""
    return os.getenv(name) or (os.getenv(fallback) if fallback else None)


def _message_text(msg: Any) -> str:
    """Extract normalized text from lark-oapi channel message objects."""
    for attr in ("content_text", "text", "message"):
        value = getattr(msg, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(getattr(msg, "content", "") or "").strip()


def _chat_id(msg: Any) -> str:
    """Extract chat ID across lark-oapi channel object variants."""
    direct = getattr(msg, "chat_id", None)
    if direct:
        return str(direct)

    conversation = getattr(msg, "conversation", None)
    if conversation is not None:
        conv_chat_id = getattr(conversation, "chat_id", None)
        if conv_chat_id:
            return str(conv_chat_id)

    return ""


def _final_text(response: Any) -> str:
    """Extract final text from an Anthropic response object."""
    parts = [
        block.text
        for block in getattr(response, "content", []) or []
        if hasattr(block, "text")
    ]
    return "".join(parts).strip() or "(no response)"


def _build_registry() -> ToolRegistry:
    """Build the same local tool registry used by the CLI app."""
    registry = ToolRegistry()
    register_bash_tool(registry)
    register_file_tools(registry)
    register_ledger_tools(registry)
    register_skill_tools(registry)
    register_web_search_tools(registry)
    register_ask_user_tool(registry)
    register_memory_tools(registry)
    register_subagent_tool(registry)
    return registry


def _build_bus() -> EventBus:
    """Create an EventBus with the standard CLI hooks."""
    bus = EventBus()
    stats = _hook_stats()
    bus.on("session_start", stats)
    bus.on("post_tool_use", stats)
    bus.on("session_end", stats)

    timer = _hook_timer()
    bus.on("pre_tool_use", timer)
    bus.on("post_tool_use", timer)
    return bus


def run_feishu_bot() -> None:
    """Connect to Feishu through WebSocket long connection and serve messages."""
    load_dotenv(override=True)

    app_id = _env("FEISHU_APP_ID", "LARK_APP_ID")
    app_secret = _env("FEISHU_APP_SECRET", "LARK_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError(
            "Missing Feishu credentials. Set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET in .env."
        )

    try:
        from lark_oapi.channel import FeishuChannel
    except ImportError as exc:
        raise RuntimeError(
            "Missing optional dependency 'lark-oapi'. Install with: "
            "uv sync --extra feishu or uv run --extra feishu s-agent-feishu"
        ) from exc

    model_id = get_default_model()
    client = create_client()
    bus = _build_bus()
    registry = _build_registry()

    asyncio.run(init_mcp(registry))
    mcp_exec = _mcp_execute if MCP_CLIENT and MCP_CLIENT.configured else None

    channel = FeishuChannel(app_id=app_id, app_secret=app_secret)
    sessions: dict[str, dict[str, Any]] = {}

    async def on_message(msg: Any) -> None:
        chat_id = _chat_id(msg)
        user_text = _message_text(msg)
        if not chat_id or not user_text:
            return

        session = sessions.setdefault(chat_id, create_session())
        session["title"] = session.get("title") or f"Feishu {chat_id}"
        session["messages"].append({"role": "user", "content": user_text})

        ctx = AgentContext(
            client=client,
            model=model_id,
            bus=bus,
            session=session,
            mcp_executor=mcp_exec,
            use_permissions=True,
            console=console,
        )
        accounting = SessionAccounting(model=model_id)
        bus.emit("session_start")

        try:
            response = await stream_loop(
                messages=session["messages"],
                registry=registry,
                system=build_system_prompt(),
                ctx=ctx,
                accounting=accounting,
            )
            await channel.send(chat_id, {"text": _final_text(response)})
        except Exception as exc:
            console.print(f"[red][feishu] message handling failed: {exc}[/red]")
            await channel.send(chat_id, {"text": f"Error: {exc}"})
        finally:
            bus.emit("session_end")
            save_session(session)

    channel.on("message", on_message)

    console.print(
        f"[dim]S-Agent Feishu bot | model={model_id} | "
        f"tools={len(registry)} | skills={len(discover_skills())}[/dim]"
    )
    console.print("[dim]Connecting to Feishu long-connection channel...[/dim]")
    try:
        channel.start()
    finally:
        if MCP_CLIENT:
            asyncio.run(MCP_CLIENT.close())


def main() -> None:
    """Console script entry point for s-agent-feishu."""
    try:
        run_feishu_bot()
    except KeyboardInterrupt:
        console.print("\n  Feishu bot interrupted. Goodbye.")
