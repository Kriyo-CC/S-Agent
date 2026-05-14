"""Config loading: .env, Anthropic client factory, permission rules.

No module-level side effects — every function is a pure factory or predicate.
The old `client` and `MODEL` globals have been replaced by `create_client()`
and `get_default_model()` so the caller (cli/app.py) can inject them via
AgentContext.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

# ── .env ────────────────────────────────────────────────
load_dotenv(override=True)

ROOT_DIR = Path(__file__).parent.parent

# ── Anthropic Client Factory ────────────────────────────


def create_client() -> Anthropic:
    """Create an Anthropic client from environment variables.

    Reads ANTHROPIC_BASE_URL (optional, for proxy/self-host) and
    ANTHROPIC_AUTH_TOKEN handling for custom endpoints.
    """
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    return Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))


def get_default_model() -> str:
    """Return the default model ID from MODEL_ID env or a sensible fallback."""
    return os.getenv("MODEL_ID", "claude-sonnet-4-20250514")


# ── Permission Rules ────────────────────────────────────
_PERM_CONFIG = ROOT_DIR / "config" / "permissions.yaml"
_perm_console = Console()  # local console for interactive prompts


def load_rules() -> Dict[str, List[Dict[str, str]]]:
    """Load permission rules from YAML configuration."""
    try:
        with open(_PERM_CONFIG, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"always_deny": [], "always_allow": [], "ask_user": []}


def check_permission(
    tool_name: str, input_str: str, rules: Optional[dict] = None
) -> Tuple[bool, str]:
    """Evaluate if a tool call is allowed based on security rules.

    Priority: always_deny → always_allow → ask_user → default allow.

    Returns (allowed: bool, reason: str). The caller is responsible for
    rendering the decision via cli/render.py — this function does NOT print.
    """
    if rules is None:
        rules = load_rules()

    for rule in rules.get("always_deny", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "blocked by policy")
            return False, f"Denied: {reason}"

    for rule in rules.get("always_allow", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            return True, "allowed by policy"

    for rule in rules.get("ask_user", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "requires user confirmation")
            _perm_console.print(
                f"\n[yellow][PERMISSION] {tool_name}: {input_str[:100]}[/yellow]"
            )
            _perm_console.print(f"[yellow]  Reason: {reason}[/yellow]")
            try:
                ans = input("  Allow? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return (ans in ("y", "yes")), "user decision"

    return True, "allowed by default"
