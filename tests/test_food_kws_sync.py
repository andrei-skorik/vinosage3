"""Sync guard for the triple anti-hallucination defense (Phase 3, step 3).

VARIANT A (approved): the three layers keep their deliberately independent
COPIES of the food-keyword data and matching logic — nothing is merged or
shared (CLAUDE.md sacred invariant). This test is the synchronization
mechanism instead: the first person who adds a food noun to one layer and
forgets the others gets a red build, with a diff of exactly what's missing.

Context: this drift already happened once. 30 nouns (prawn, crab, soup,
stew, burger, scallop, ...) were added to layer 1 over time while layers
2/3 and the routing set silently lagged — degrading defense-in-depth to a
single layer for those foods. Step 3 fixed the drift; this file keeps it
fixed.

The three layers under guard:
  L1  src/tools/pair_with_food.py  _FOOD_NOUNS   + _PAIRING_TRIGGER_RE
  L2  src/agent.py                 _FOOD_KWS     + _PAIRING_TRIGGER_RE
  L3  app.py                       _HIST_FOOD_KWS + _HISTORY_PAIRING_TRIGGER_RE

Related but DIFFERENT mechanism (not forced equal):
  src/agent.py _FOOD_QUERY_KWS — multilingual routing/detection set. It
  intentionally CONTAINS "cake" (a cake query must be detected as a food
  query) and DE/FI words. Its contract here: it must recognize at least
  every English evidence noun (superset assertion), or routing misses food
  queries that the evidence layers could handle.
"""
from __future__ import annotations

import pytest

import app
from src import agent
from src.tools.pair_with_food import _FOOD_NOUNS
from src.tools.pair_with_food import _PAIRING_TRIGGER_RE as _L1_TRIGGER_RE


# ── Data sync: the three evidence keyword sets ────────────────────────────────


def test_three_evidence_sets_are_identical():
    """The whole point of variant A. On failure, pytest shows the exact
    missing/extra words — add them to EVERY layer, not just one."""
    l1 = set(_FOOD_NOUNS)
    l2 = set(agent._FOOD_KWS)
    l3 = set(app._HIST_FOOD_KWS)
    assert l1 == l2, f"L1 vs L2 drift: only-L1={sorted(l1-l2)} only-L2={sorted(l2-l1)}"
    assert l1 == l3, f"L1 vs L3 drift: only-L1={sorted(l1-l3)} only-L3={sorted(l3-l1)}"


def test_cake_is_intentionally_absent_from_all_evidence_sets():
    """'cake' must never become an extractable evidence keyword (it matches
    Madeira cake / fish cakes in descriptions — see _FOOD_NOUNS comment)."""
    assert "cake" not in _FOOD_NOUNS
    assert "cake" not in agent._FOOD_KWS
    assert "cake" not in app._HIST_FOOD_KWS


def test_cake_stays_in_the_routing_set():
    """...but routing MUST still detect 'what wine with cake?' as a food
    query, so pair_with_food is forced. Two different mechanisms, two
    different (correct) answers about 'cake'."""
    assert "cake" in agent._FOOD_QUERY_KWS


def test_routing_recognizes_every_evidence_noun():
    """If a noun can serve as pairing evidence (L1), the router must detect a
    query containing it as a food query — otherwise layers 2/3 never engage
    and pair_with_food is not structurally forced. This is exactly the gap
    the 30-noun drift opened."""
    missing = set(_FOOD_NOUNS) - set(agent._FOOD_QUERY_KWS)
    assert not missing, f"Routing set lags evidence set by: {sorted(missing)}"


# ── Logic sync: the three trigger regexes ─────────────────────────────────────


def test_three_pairing_trigger_regexes_are_identical():
    """The trigger-anchoring logic is duplicated by design; the PATTERNS must
    stay in lockstep. Compare source pattern and flags, not object identity."""
    p1, p2, p3 = (
        _L1_TRIGGER_RE,
        agent._PAIRING_TRIGGER_RE,
        app._HISTORY_PAIRING_TRIGGER_RE,
    )
    assert p1.pattern == p2.pattern == p3.pattern
    assert p1.flags == p2.flags == p3.flags


# ── Behavioral regressions on the drift that actually happened ───────────────
# 'prawns' was one of the 30 nouns missing from layers 2/3. These tests pin
# the post-fix behavior: the evidence filter must engage for it.


class _Wine:
    """Duck-typed RetrievedWine."""
    def __init__(self, title: str, description: str):
        self.wine_id = f"w-{title}"
        self.title = title
        self.similarity = 0.9
        self.payload = {
            "type": "White", "grape": "Albariño", "country": "Spain",
            "style": "Crisp & Zesty", "price_eur_cents": 1499,
            "description": description,
        }


_EVIDENCE_WINE = _Wine(
    "Mar de Frades",
    "Bright and saline. Try it with grilled prawns and shellfish.",
)
_TASTING_NOTE_WINE = _Wine(
    "Prawn Star",  # brand name only — capitalised, and no pairing trigger
    "Notes of citrus and wet stone with a creamy texture.",
)


def test_layer2_rag_filter_engages_for_previously_missing_noun():
    """agent._build_messages: for a 'prawns' query, only trigger-anchored
    prawn evidence may enter the RAG context block. Before the drift fix the
    filter never engaged for 'prawns' and BOTH wines leaked into context."""
    messages = agent._build_messages(
        query="what wine goes with prawns?",
        locale="en",
        history=None,
        rag_context=[_EVIDENCE_WINE, _TASTING_NOTE_WINE],
    )
    system_ctx = "\n".join(
        m["content"] for m in messages
        if m["role"] == "system" and "Catalog" in m["content"]
    )
    assert "Mar de Frades" in system_ctx
    assert "Prawn Star" not in system_ctx


def test_layer3_history_filter_engages_for_previously_missing_noun():
    """app._agent_history: same guarantee for historical sources on a
    follow-up turn in prawn context."""
    messages = [
        {"role": "user", "content": "what goes with prawns?"},
        {
            "role": "assistant",
            "content": "Here are options.",
            "sources": [_EVIDENCE_WINE, _TASTING_NOTE_WINE],
        },
    ]
    history = app._agent_history(messages, current_query="is that the only prawn option?")
    joined = "\n".join(m["content"] for m in history if m["role"] == "system")
    assert "Mar de Frades" in joined
    assert "Prawn Star" not in joined


def test_routing_detects_previously_missing_noun():
    """agent._is_food_query must now fire for the once-missing nouns."""
    assert agent._is_food_query("what wine goes with prawns?", None) is True
    assert agent._is_food_query("recommend a wine for my seafood stew", None) is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
