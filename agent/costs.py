"""Per-model token cost lookup table.

All prices are per-million-tokens in USD. Sources:
- Claude models: https://docs.anthropic.com/en/docs/about-claude/pricing
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing
- GPT models: https://openai.com/pricing

Each entry: (input_per_mtok, output_per_mtok)
"""

# ── Anthropic Claude ──────────────────────────────────────
CLAUDE_SONNET_4_20250514 = (3.0, 15.0)
CLAUDE_SONNET_4 = (3.0, 15.0)
CLAUDE_OPUS_4_7 = (15.0, 75.0)
CLAUDE_HAIKU_4_5 = (0.80, 4.0)

# ── DeepSeek ──────────────────────────────────────────────
DEEPSEEK_V4_FLASH = (0.50, 2.0)
DEEPSEEK_CHAT = (0.27, 1.10)
DEEPSEEK_REASONER = (0.55, 2.19)

# ── OpenAI ────────────────────────────────────────────────
GPT_4O = (2.50, 10.0)
GPT_4O_MINI = (0.15, 0.60)

# ── Mapping ───────────────────────────────────────────────
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": CLAUDE_SONNET_4_20250514,
    "claude-sonnet-4": CLAUDE_SONNET_4,
    "claude-opus-4-7": CLAUDE_OPUS_4_7,
    "claude-haiku-4-5-20251001": CLAUDE_HAIKU_4_5,
    "claude-haiku-4-5": CLAUDE_HAIKU_4_5,
    "deepseek-v4-flash": DEEPSEEK_V4_FLASH,
    "deepseek-chat": DEEPSEEK_CHAT,
    "deepseek-reasoner": DEEPSEEK_REASONER,
    "gpt-4o": GPT_4O,
    "gpt-4o-mini": GPT_4O_MINI,
}


def get_cost_per_token(model: str) -> tuple[float, float]:
    """Return (input_cost_per_token, output_cost_per_token) for a model.

    Falls back to (0, 0) for unknown models.
    """
    rates = _MODEL_COSTS.get(model)
    if rates is None:
        return (0.0, 0.0)
    return (rates[0] / 1_000_000, rates[1] / 1_000_000)


def calculate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Calculate total cost in USD for a single API call."""
    input_rate, output_rate = get_cost_per_token(model)
    return round(input_tokens * input_rate + output_tokens * output_rate, 6)
