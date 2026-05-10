"""Config loading: .env, Anthropic client, permission rules."""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

# ── .env ────────────────────────────────────────────────
load_dotenv(override=True)

ROOT_DIR = Path(__file__).parent.parent

# ── Anthropic Client ────────────────────────────────────
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")

# ── Dangerous Command Blacklist ─────────────────────────
ALWAYS_BLOCK = [
    "rm -rf /",
    "sudo",
    "shutdown",
    "reboot",
    "> /dev/",
    ":(){ :|:& };:",
]

# ── Permission Rules ────────────────────────────────────
_PERM_CONFIG = ROOT_DIR / "config" / "permissions.yaml"


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
    """
    if rules is None:
        rules = load_rules()

    for rule in rules.get("always_deny", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "blocked by policy")
            print(f"\033[31m[DENIED] {reason}\033[0m")
            return False, f"Denied: {reason}"

    for rule in rules.get("always_allow", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            return True, "allowed by policy"

    for rule in rules.get("ask_user", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "requires user confirmation")
            print(f"\n\033[33m[PERMISSION] {tool_name}: {input_str[:100]}")
            print(f"  Reason: {reason}\033[0m")
            try:
                ans = input("  Allow? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return (ans in ("y", "yes")), "user decision"

    return True, "allowed by default"
