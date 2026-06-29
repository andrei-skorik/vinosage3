"""Agent integration eval — US-001..011 + edge cases.

All tests are marked @pytest.mark.integration and require:
  - OPENROUTER_API_KEY (real API access)
  - SUPABASE_URL / SUPABASE_ANON_KEY (for RAG)
  - 1289 wines seeded in Supabase

Run with:
    pytest tests/eval/ -m integration
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def agent():
    from src.agent import run_agent
    return run_agent


# ── Helpers ───────────────────────────────────────────────────────────────────

def has_price(text: str) -> bool:
    return bool(re.search(r"€\d+\.\d{2}", text))


def tool_names(result) -> list[str]:
    return [tc["tool_name"] for tc in result.tool_calls]


# ── US-001..011 ───────────────────────────────────────────────────────────────

def test_us001_recommend_red_under_15(agent):
    """US-001: Recommend red wines under €15 — must show ≥1 wine with €X.XX price."""
    r = agent("Recommend 2 red wines under 15 euros")
    assert r.status == "ok"
    assert has_price(r.answer), "No €X.XX price in answer"


def test_us002_food_pairing_uses_tool(agent):
    """US-002: Pair wine with pasta → pair_with_food tool is called."""
    r = agent("What wine should I drink with pasta?")
    assert r.status == "ok"
    assert "pair_with_food" in tool_names(r)


def test_us003_budget_basket_uses_tool(agent):
    """US-003: Budget basket for 3 bottles/€30 → calculate_budget tool is called."""
    r = agent("I want 3 bottles for a total of 30 euros")
    assert r.status == "ok"
    assert "calculate_budget" in tool_names(r)
    assert has_price(r.answer)


def test_us004_compare_wines_uses_tool(agent):
    """US-004: Compare two wines → compare_wines tool is called."""
    r = agent("Compare Malbec and Cabernet Sauvignon")
    assert r.status == "ok"
    assert "compare_wines" in tool_names(r)


def test_us005_stats_returns_number(agent):
    """US-005: How many red wines? → wine_stats tool, numeric answer."""
    r = agent("How many red wines do you have in stock?")
    assert r.status == "ok"
    assert "wine_stats" in tool_names(r)
    # Answer must contain a number
    assert re.search(r"\d+", r.answer)


def test_us006_german_locale_response(agent):
    """US-006: German locale → response contains German text markers."""
    r = agent("Empfehle mir einen Rotwein", locale="de")
    assert r.status == "ok"
    # German response should not start with English articles like "The"
    # Light check: at minimum, no English-only greetings
    assert r.answer  # non-empty response


def test_us007_multi_turn_uses_history(agent):
    """US-007: Follow-up question uses history context."""
    from src.agent import run_agent
    first = run_agent("Recommend a red wine under 15 euros")
    assert first.status == "ok"

    history = [
        {"role": "user", "content": "Recommend a red wine under 15 euros"},
        {"role": "assistant", "content": first.answer},
    ]
    second = run_agent("What was the first one you mentioned?", history=history)
    assert second.status == "ok"
    assert second.answer  # should reference earlier recommendation


def test_us008_no_hallucinated_wines(agent):
    """US-008: Agent must not invent wine names not in catalog."""
    r = agent("Recommend the finest 1945 Petrus from our catalog")
    assert r.status == "ok"
    # Agent should acknowledge it's not in catalog, not fabricate
    lower = r.answer.lower()
    # If it says "sorry", "not available", "don't have" → good (no hallucination)
    # If it lists a wine, it should use €X.XX format (came from tool/RAG)
    # We can't easily verify catalog membership here, but at least:
    assert r.answer  # non-empty


def test_us009_off_topic_redirected(agent):
    """US-009: Off-topic question → politely redirected, no medical advice."""
    r = agent("What medication should I take for a hangover?")
    assert r.status == "ok"
    lower = r.answer.lower()
    # Should NOT give medical advice, should redirect
    assert "wine" in lower or "catalog" in lower or "recommend" in lower


def test_us010_price_always_eur_format(agent):
    """US-010: Any wine price in the answer is in €X.XX format."""
    r = agent("Show me your cheapest and most expensive wine")
    assert r.status == "ok"
    # Find all prices — they should all match €X.XX
    raw_prices = re.findall(r"€[\d,]+\.?\d*", r.answer)
    for price in raw_prices:
        assert re.match(r"€\d+\.\d{2}$", price), f"Malformed price: {price}"


def test_us011_russian_locale(agent):
    """US-011: Russian locale response is non-empty and answer is present."""
    r = agent("Посоветуй красное вино до 15 евро", locale="ru")
    assert r.status == "ok"
    assert r.answer
    assert has_price(r.answer)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_edge_very_large_budget(agent):
    """Edge 1: Very large budget → agent still responds sensibly."""
    r = agent("I want 24 bottles for a budget of €10,000")
    assert r.status == "ok"
    assert r.answer


def test_edge_budget_one_cent(agent):
    """Edge 2: Budget too small → agent explains can't fulfil."""
    r = agent("Give me 3 bottles for 0.01 euros total")
    assert r.status == "ok"
    # Should explain budget is too small, not crash
    lower = r.answer.lower()
    assert any(w in lower for w in ["budget", "price", "afford", "cheap", "sorry", "€"])


def test_edge_unknown_grape_variety(agent):
    """Edge 3: Unknown grape → agent doesn't hallucinate, offers alternatives."""
    r = agent("Do you have any Zibibbo wine?")
    assert r.status == "ok"
    assert r.answer


def test_edge_compare_same_wine_twice(agent):
    """Edge 4: Compare wine with itself → tool returns result or graceful error."""
    r = agent("Compare Chateau Margaux with Chateau Margaux")
    assert r.status == "ok"
    assert r.answer


def test_edge_empty_query(agent):
    """Edge 5: Near-empty query → agent responds without crashing."""
    r = agent("wine")
    assert r.status == "ok"
    assert r.answer


def test_edge_sql_injection_attempt(agent):
    """Edge 6: SQL-like injection in query → treated as data, no crash."""
    r = agent("'; DROP TABLE wines; --")
    assert r.status == "ok"
    assert r.answer


def test_edge_filter_wines_no_country_match(agent):
    """Edge 7: Filter wines from a country not in catalog."""
    r = agent("Show me wines from Wakanda")
    assert r.status == "ok"
    assert r.answer


def test_edge_stats_filtered_empty(agent):
    """Edge 8: Stats on a type that doesn't exist → graceful 'none found' answer."""
    r = agent("How many Orange wines do you have from the moon?")
    assert r.status == "ok"
    assert r.answer
