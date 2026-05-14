"""Rich console wrapper — shared Console instance and style helpers.

All user-facing output goes through this module to ensure consistent
styling and a single point of control for output formatting.
Diagnostics use Python logging, not this module.
"""

from rich.console import Console

console = Console()


def print_error(msg: str) -> None:
    """Bright red error message."""
    console.print(f"[red]Error: {msg}[/red]")


def print_warning(msg: str) -> None:
    """Yellow warning message."""
    console.print(f"[yellow]{msg}[/yellow]")


def print_info(msg: str) -> None:
    """Dimmed info / status message."""
    console.print(f"[dim]{msg}[/dim]")


def print_tool_call(tool_name: str, summary: str) -> None:
    """Tool invocation line: yellow name + summary."""
    console.print(f"[yellow]{tool_name}[/yellow] {summary}")


def print_subagent(msg: str) -> None:
    """Subagent-related message in magenta."""
    console.print(f"[magenta]{msg}[/magenta]")


def print_session_id(session_id: str) -> None:
    """Session ID in cyan."""
    console.print(f"[cyan]{session_id}[/cyan]")


def print_dim(msg: str) -> None:
    """Low-priority dimmed text."""
    console.print(f"[dim]{msg}[/dim]")


def print_bold(msg: str) -> None:
    """Bold title/heading."""
    console.print(f"[bold]{msg}[/bold]")


def rule(title: str) -> None:
    """Horizontal rule with centered title."""
    console.rule(f"[bold]{title}[/bold]")
