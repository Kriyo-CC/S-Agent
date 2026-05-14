"""REPL command handlers.

Each handler returns an indication of whether the command was handled.
The REPL loop in repl.py calls handle_command() before falling through
to sending the input to the agent loop.
"""

from datetime import datetime
from typing import Dict, Any, Optional

from agent.session import (
    load_session,
    save_session,
    print_sessions_table,
)
from agent.accounting import SessionAccounting
from cli.render import console


def cmd_sessions() -> bool:
    """List all saved sessions."""
    print_sessions_table()
    return True


def cmd_resume(query: str, session: Dict[str, Any]) -> bool:
    """Resume a session by ID prefix."""
    target = query[8:].strip()
    loaded = load_session(target)
    if loaded:
        session.update(loaded)
        mc = len(session.get("messages", []))
        console.print(
            f"  Resumed: [cyan]{session['id']}[/cyan] "
            f"— '{session['title']}' ({mc} msgs)"
        )
    else:
        console.print(f"[red]Error: Session '{target}' not found.[/red]")
    return True


def cmd_fork(query: str, session: Dict[str, Any]) -> bool:
    """Fork a session by ID prefix into the current session."""
    src_id = query[6:].strip()
    src = load_session(src_id)
    if src:
        session["id"] = f"fork-{src['id'][:4]}"
        session["title"] = f"Fork of {src['title'][:30]}"
        session["messages"] = src.get("messages", [])
        session["created"] = datetime.now().isoformat()
        console.print(f"  Forked {src_id} → [cyan]{session['id']}[/cyan]")
    else:
        console.print(f"[red]Error: Session '{src_id}' not found.[/red]")
    return True


def cmd_title(query: str, session: Dict[str, Any]) -> bool:
    """Set the session title."""
    session["title"] = query[7:].strip()
    console.print(f"  Title: '{session['title']}'")
    return True


def cmd_save(session: Dict[str, Any]) -> bool:
    """Save the current session."""
    save_session(session)
    console.print(f"  Saved: {session['id']}")
    return True


def cmd_tools(registry) -> bool:
    """List all registered tools."""
    console.print("  " + ", ".join(registry.list_names()))
    return True


def cmd_accounting(accounting: SessionAccounting) -> bool:
    """Display token usage and cost for the current session."""
    accounting.display_summary()
    return True


def handle_command(
    query: str,
    session: Dict[str, Any],
    registry,
    accounting: Optional[SessionAccounting] = None,
) -> bool:
    """Dispatch a :command. Returns True if query was a command."""
    if query == ":sessions":
        return cmd_sessions()

    if query.startswith(":resume "):
        return cmd_resume(query, session)

    if query.startswith(":fork "):
        return cmd_fork(query, session)

    if query.startswith(":title "):
        return cmd_title(query, session)

    if query == ":save":
        return cmd_save(session)

    if query == ":tools":
        return cmd_tools(registry)

    if query == ":accounting":
        if accounting:
            return cmd_accounting(accounting)
        console.print("[yellow]  Accounting not available.[/yellow]")
        return True

    return False
