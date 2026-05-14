"""Bash tools: execute shell commands.

Two tools are provided:
- `bash` (safe) — uses shlex.split() + no shell=True. No pipes/redirects/env vars.
- `bash_shell` (opt-in) — uses shell=True for when you need pipes, redirects, or
  shell builtins. Carries command injection risk.
"""

import os
import shlex
import subprocess
from typing import Dict, Any


def run_bash(command: str) -> str:
    """Execute a single command safely with no shell interpretation.

    Uses shlex.split() and list-form subprocess.run() — no shell=True,
    meaning pipes, redirects, and shell builtins (cd, export) will NOT work.
    Use bash_shell if those are needed.

    Args:
        command: The command string (e.g. "ls -la").

    Returns:
        Combined stdout+stderr, truncated to 50k characters.
    """
    try:
        args = shlex.split(command)
        if not args:
            return "Error: empty command"
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except FileNotFoundError:
        return "Error: command not found"
    except Exception as e:
        return f"Error: {e}"


def run_bash_shell(command: str) -> str:
    """Execute a command with shell=True (pipes, redirects, env vars work).

    WARNING: This carries command injection risk. The model should only use
    this when shell features are genuinely needed (pipes, heredocs, chaining).

    Args:
        command: The shell command string (e.g. "ls -la | grep foo").

    Returns:
        Combined stdout+stderr, truncated to 50k characters.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def register_bash_tool(registry) -> None:
    """Register the safe `bash` tool (no shell=True)."""
    registry.register(
        name="bash",
        description=(
            "Execute a shell command safely. Uses shlex.split() — no shell "
            "interpretation. Pipes, redirects, env vars, and shell builtins "
            "(cd, export) will NOT work. For those, use bash_shell instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute (e.g. 'ls -la').",
                }
            },
            "required": ["command"],
        },
        handler=lambda inp: run_bash(inp["command"]),
    )

    registry.register(
        name="bash_shell",
        description=(
            "Execute a command with shell=True. Supports pipes, redirects, "
            "env vars, and shell builtins. WARNING: command injection risk — "
            "only use when bash's shlex-based tool cannot handle the command."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                }
            },
            "required": ["command"],
        },
        handler=lambda inp: run_bash_shell(inp["command"]),
    )
