"""Bash tool: execute shell commands with safety checks."""

import os
import subprocess
from typing import Dict, Any

from config.settings import ALWAYS_BLOCK, check_permission


def run_bash(command: str) -> str:
    """Execute a shell command synchronously with safety checks.

    Args:
        command: The shell command to execute.

    Returns:
        Combined stdout+stderr, truncated to 50k characters.
    """
    if any(blocked in command for blocked in ALWAYS_BLOCK):
        return "Error: dangerous command blocked"

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
    registry.register(
        name="bash",
        description="Run a shell command.",
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
        handler=lambda inp: run_bash(inp["command"]),
    )
