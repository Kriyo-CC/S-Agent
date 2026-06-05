"""Tests for cache-aware token accounting."""

from types import SimpleNamespace

from agent.accounting import SessionAccounting
from agent.costs import calculate_cost, format_cost, get_currency
from agent.loop import _extract_billable_usage


def test_deepseek_v4_flash_cache_aware_cost() -> None:
    # 1M cache-miss input at 1 CNY + 1M cache-hit input at 0.02 CNY
    # + 1M output at 2 CNY = 3.02 CNY.
    cost = calculate_cost(
        "deepseek-v4-flash",
        input_tokens=1_000_000,
        cached_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 3.02
    assert get_currency("deepseek-v4-flash") == "CNY"
    assert format_cost("deepseek-v4-flash", cost) == "¥3.0200"


def test_deepseek_v4_pro_cache_aware_cost() -> None:
    # 1M cache-miss input at 3 CNY + 1M cache-hit input at 0.025 CNY
    # + 1M output at 6 CNY = 9.025 CNY.
    cost = calculate_cost(
        "deepseek-v4-pro",
        input_tokens=1_000_000,
        cached_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 9.025
    assert format_cost("deepseek-v4-pro", cost) == "¥9.0250"


def test_extract_billable_usage_from_anthropic_cache_fields() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        cache_creation_input_tokens=30,
        cache_read_input_tokens=200,
        output_tokens=50,
    )

    assert _extract_billable_usage(usage) == (130, 200, 50)


def test_extract_billable_usage_from_deepseek_alias_fields() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        prompt_cache_miss_tokens=20,
        prompt_cache_hit_tokens=300,
        output_tokens=40,
    )

    assert _extract_billable_usage(usage) == (120, 300, 40)


def test_session_accounting_summarizes_cached_tokens() -> None:
    accounting = SessionAccounting(model="deepseek-v4-flash")
    accounting.record_turn(
        input_tokens=1_000_000,
        cached_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert accounting.total_input_tokens == 1_000_000
    assert accounting.total_cached_input_tokens == 1_000_000
    assert accounting.total_output_tokens == 1_000_000
    assert accounting.total_cost == 3.02
    summary = accounting.summary()
    assert "Currency: CNY" in summary
    assert "Input tokens (cache hit): 1,000,000" in summary
    assert "¥3.0200" in summary
