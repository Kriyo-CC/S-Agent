"""REPL loop — reads user input, dispatches commands, runs the agent loop.

This is the interactive front-end of the scaffold. The loop:
1. Prints a prompt and reads user input
2. Dispatches :commands to commands.py
3. Sends regular input to stream_loop
4. Runs post-turn maintenance (compress, save)
"""

from cli.render import console
from cli.commands import handle_command
from agent.loop import stream_loop
from agent.context import maybe_compress
from agent.prompt import build_system_prompt
from agent.session import save_session
from agent.accounting import SessionAccounting
from agent.types import AgentContext
from tools.registry import ToolRegistry


async def run_repl(ctx: AgentContext, registry: ToolRegistry) -> None:
    """Run the REPL loop until the user exits.

    Args:
        ctx: AgentContext with client, model, bus, session, console.
        registry: ToolRegistry with all registered tools.
    """
    session = ctx.session
    bus = ctx.bus

    # ── Accounting ────────────────────────────────────
    accounting = SessionAccounting(model=ctx.model)

    bus.emit("session_start")

    try:
        while True:
            try:
                query = console.input(
                    f"[cyan]agent ({session['id']}) >> [/cyan]"
                ).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n  Exiting...")
                break

            if not query:
                continue

            if query.lower() in ("q", "exit", "quit"):
                break

            if handle_command(query, session, registry, accounting=accounting):
                continue

            # Auto-title on first message
            if not session["messages"]:
                session["title"] = query[:50]

            # Append user message and run agent loop
            session["messages"].append({"role": "user", "content": query})
            await stream_loop(
                messages=session["messages"],
                registry=registry,
                system=build_system_prompt(),
                ctx=ctx,
                accounting=accounting,
            )

            # Post-turn maintenance
            maybe_compress(session["messages"], ctx)
            save_session(session)
            console.print()

    finally:
        bus.emit("session_end")
        if accounting.turn_count > 0:
            accounting.display_summary()
        save_session(session)
