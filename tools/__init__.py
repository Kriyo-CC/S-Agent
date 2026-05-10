"""Tools package for the agent scaffold.

All tools are registered into a ToolRegistry. New tools can be added by
creating a module with a `register_<name>_tool(registry)` function.
"""

from tools.registry import ToolRegistry
from tools.bash import register_bash_tool
from tools.file_ops import register_file_tools
from tools.ledger import register_ledger_tools
from tools.skill import register_skill_tools, discover_skills
from tools.subagent import register_subagent_tool


def build_default_registry() -> ToolRegistry:
    """Build and return a ToolRegistry with all built-in tools registered."""
    registry = ToolRegistry()
    register_bash_tool(registry)
    register_file_tools(registry)
    register_ledger_tools(registry)
    register_skill_tools(registry)
    # subagent is registered after we have the full tool list,
    # so it gets registered later in main.py
    return registry
