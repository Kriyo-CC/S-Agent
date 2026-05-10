"""Skill tools: on-demand discovery and loading of SKILL.md files.

Skills are stored in the skills/ directory as subdirectories containing
a SKILL.md file. The agent discovers available skills at startup and can
load full instructions on demand, keeping the system prompt lean.
"""

import re
from pathlib import Path
from typing import Dict

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def discover_skills() -> Dict[str, str]:
    """Scan skills/ directory, returning {name: short_description}.

    Extracts description from YAML frontmatter (description: key) first,
    falls back to first non-heading body text line.
    """
    skills: Dict[str, str] = {}
    if not SKILLS_DIR.exists():
        return skills

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if skill_dir.is_dir() and skill_md.exists():
            try:
                body = skill_md.read_text(encoding="utf-8")
                description = "No description available."

                # Try YAML frontmatter description first
                fm_match = re.match(r"^---\s*\n(.*?)\n---", body, re.DOTALL)
                if fm_match:
                    fm = fm_match.group(1)
                    desc_match = re.search(
                        r"^\s*description\s*:\s*(.+)$", fm, re.MULTILINE
                    )
                    if desc_match:
                        description = desc_match.group(1).strip()[:100]

                # Fallback: first non-heading, non-empty body line
                if description == "No description available.":
                    in_frontmatter = False
                    for line in body.splitlines():
                        stripped = line.strip()
                        if stripped == "---":
                            in_frontmatter = not in_frontmatter
                            continue
                        if (
                            not in_frontmatter
                            and stripped
                            and not stripped.startswith("#")
                        ):
                            description = stripped[:100]
                            break

                skills[skill_dir.name] = description
            except Exception as e:
                skills[skill_dir.name] = f"Error: {e}"
    return skills


def run_list_skills() -> str:
    """Format the list of available skills for the agent."""
    skills = discover_skills()
    if not skills:
        return "(no skills found in skills/ directory)"
    return "\n".join(f"  - {n}: {d}" for n, d in skills.items())


def run_load_skill(name: str) -> str:
    """Load the full content of a specific SKILL.md file."""
    if not name or not name.strip():
        return "Error: skill name cannot be empty. Use list_skills to see valid names."
    # Prevent path traversal attacks
    if ".." in name or "/" in name or "\\" in name:
        return f"Error: invalid skill name '{name}'."
    skill_path = SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        return f"Error: skill '{name}' not found. Use list_skills to see valid names."
    try:
        content = skill_path.read_text(encoding="utf-8")
        return f"=== SKILL: {name} ===\n\n{content}\n\n=== END SKILL ==="
    except Exception as e:
        return f"Error loading skill '{name}': {e}"


def register_skill_tools(registry) -> None:
    registry.register(
        name="list_skills",
        description="List all available specialized skills with brief descriptions.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda inp: run_list_skills(),
    )
    registry.register(
        name="load_skill",
        description=(
            "Load the full instructions for a skill into your context. "
            "Use this before a task requiring specialized domain knowledge."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The exact name of the skill to load.",
                }
            },
            "required": ["name"],
        },
        handler=lambda inp: run_load_skill(inp["name"]),
    )
