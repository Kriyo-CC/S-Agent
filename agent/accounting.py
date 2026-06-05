"""Token usage tracking and cost calculation.

SessionAccounting records per-turn token usage and can produce a summary
for display via the :accounting REPL command or session-end report.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from agent.costs import calculate_cost, format_cost, get_currency
from cli.render import console


@dataclass
class TurnCost:
    """Cost record for a single turn in the agent loop."""

    turn: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost: float
    timestamp: str


class SessionAccounting:
    """Per-session token and cost tracker.

    Usage:
        acct = SessionAccounting(model="claude-sonnet-4-20250514")
        acct.record_turn(input_tokens=500, output_tokens=200)
        print(acct.summary())
    """

    def __init__(self, model: str):
        self.model = model
        self.turns: list[TurnCost] = []
        self._total_input = 0
        self._total_cached_input = 0
        self._total_output = 0
        self._total_cost = 0.0

    def record_turn(
        self,
        input_tokens: int,
        output_tokens: int,
        turn_number: Optional[int] = None,
        cached_input_tokens: int = 0,
    ) -> TurnCost:
        """Record token usage for one turn and return the TurnCost record."""
        cost = calculate_cost(
            self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
        )
        turn = turn_number if turn_number is not None else len(self.turns) + 1
        now = datetime.now().isoformat()

        record = TurnCost(
            turn=turn,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            timestamp=now,
        )
        self.turns.append(record)
        self._total_input += input_tokens
        self._total_cached_input += cached_input_tokens
        self._total_output += output_tokens
        self._total_cost += cost
        return record

    @property
    def total_input_tokens(self) -> int:
        return self._total_input

    @property
    def total_cached_input_tokens(self) -> int:
        return self._total_cached_input

    @property
    def total_output_tokens(self) -> int:
        return self._total_output

    @property
    def total_tokens(self) -> int:
        return self._total_input + self._total_cached_input + self._total_output

    @property
    def total_cost(self) -> float:
        return round(self._total_cost, 6)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def summary(self) -> str:
        """Return a human-readable summary string."""
        if not self.turns:
            return (
                f"[dim]  [accounting] Model: {self.model} | "
                f"No turns recorded yet.[/dim]"
            )
        return (
            f"[bold]── Session Accounting ──[/bold]\n"
            f"  Model: {self.model}\n"
            f"  Currency: {get_currency(self.model)}\n"
            f"  Turns: {self.turn_count}\n"
            f"  Input tokens (cache miss): {self._total_input:,}\n"
            f"  Input tokens (cache hit): {self._total_cached_input:,}\n"
            f"  Output tokens: {self._total_output:,}\n"
            f"  Total tokens: {self.total_tokens:,}\n"
            f"  Total cost: [yellow]{format_cost(self.model, self.total_cost)}[/yellow]\n"
        )

    def display_summary(self) -> None:
        """Print the summary via Rich console."""
        console.print(self.summary())
