"""Ask User tool: blocking question via the terminal.

When the agent needs clarification or a decision, this tool prompts
the user directly through the terminal and returns their response.
"""

from cli.render import console


def run_ask_user(question: str) -> str:
    """Ask the user a question and return their response.

    Args:
        question: The question to display to the user.

    Returns:
        The user's response text.
    """
    if not question or not question.strip():
        return "Error: question cannot be empty."

    console.print(f"\n[bold yellow]Agent asks:[/bold yellow] {question.strip()}")
    console.print("[dim]Type your response below (press Enter to submit).[/dim]")

    try:
        answer = console.input("[bold cyan]> [/bold cyan]")
        return answer.strip() or "(no response)"
    except (EOFError, KeyboardInterrupt):
        return "(user cancelled)"


def register_ask_user_tool(registry) -> None:
    registry.register(
        name="ask_user",
        description=(
            "Ask the user a question and get their response. Use this when you "
            "need clarification, a decision, or additional information that "
            "cannot be found in the codebase or documentation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                },
            },
            "required": ["question"],
        },
        handler=lambda inp: run_ask_user(inp["question"]),
    )
