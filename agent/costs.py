"""Per-model token cost lookup table.

Prices are per-million tokens. DeepSeek-V4 prices are in CNY and distinguish
cache-hit input from uncached/cache-miss input. Other model prices remain in
USD and use the uncached input/output rates.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostRates:
    """Per-million-token model prices."""

    input_uncached: float
    output: float
    currency: str = "USD"
    input_cached: float = 0.0


# ── Anthropic Claude (USD / million tokens) ───────────────
CLAUDE_SONNET_4_20250514 = CostRates(input_uncached=3.0, output=15.0)
CLAUDE_SONNET_4 = CostRates(input_uncached=3.0, output=15.0)
CLAUDE_OPUS_4_7 = CostRates(input_uncached=15.0, output=75.0)
CLAUDE_HAIKU_4_5 = CostRates(input_uncached=0.80, output=4.0)

# ── DeepSeek (CNY / million tokens) ───────────────────────
DEEPSEEK_V4_FLASH = CostRates(
    input_cached=0.02,
    input_uncached=1.0,
    output=2.0,
    currency="CNY",
)
DEEPSEEK_V4_PRO = CostRates(
    input_cached=0.025,
    input_uncached=3.0,
    output=6.0,
    currency="CNY",
)
DEEPSEEK_CHAT = CostRates(input_uncached=0.27, output=1.10)
DEEPSEEK_REASONER = CostRates(input_uncached=0.55, output=2.19)

# ── OpenAI (USD / million tokens) ─────────────────────────
GPT_4O = CostRates(input_uncached=2.50, output=10.0)
GPT_4O_MINI = CostRates(input_uncached=0.15, output=0.60)

# ── Mapping ───────────────────────────────────────────────
_MODEL_COSTS: dict[str, CostRates] = {
    "claude-sonnet-4-20250514": CLAUDE_SONNET_4_20250514,
    "claude-sonnet-4": CLAUDE_SONNET_4,
    "claude-opus-4-7": CLAUDE_OPUS_4_7,
    "claude-haiku-4-5-20251001": CLAUDE_HAIKU_4_5,
    "claude-haiku-4-5": CLAUDE_HAIKU_4_5,
    "deepseek-v4-flash": DEEPSEEK_V4_FLASH,
    "deepseek-v4-pro": DEEPSEEK_V4_PRO,
    "deepseek-chat": DEEPSEEK_CHAT,
    "deepseek-reasoner": DEEPSEEK_REASONER,
    "gpt-4o": GPT_4O,
    "gpt-4o-mini": GPT_4O_MINI,
}


def get_cost_rates(model: str) -> CostRates:
    """Return per-million-token rates for a model.

    Falls back to zero USD rates for unknown models.
    """
    return _MODEL_COSTS.get(model, CostRates(input_uncached=0.0, output=0.0))


def get_cost_per_token(model: str) -> tuple[float, float]:
    """Return legacy (input_uncached, output) per-token rates for a model."""
    rates = get_cost_rates(model)
    return (rates.input_uncached / 1_000_000, rates.output / 1_000_000)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Calculate total cost for a single API call.

    Args:
        model: Model ID.
        input_tokens: Uncached/cache-miss input tokens.
        output_tokens: Output tokens.
        cached_input_tokens: Cache-hit input tokens.
    """
    rates = get_cost_rates(model)
    total = (
        input_tokens * rates.input_uncached
        + cached_input_tokens * rates.input_cached
        + output_tokens * rates.output
    ) / 1_000_000
    return round(total, 6)


def get_currency(model: str) -> str:
    """Return the billing currency for a model."""
    return get_cost_rates(model).currency


def format_cost(model: str, amount: float) -> str:
    """Format a model cost with the right currency symbol."""
    currency = get_currency(model)
    symbol = "¥" if currency == "CNY" else "$"
    return f"{symbol}{amount:.4f}"
