"""Regression test for explicit-only preference extraction (Phase 3 / v3.0,
step 6, gap #2).

SPEC invariant (§5.3): `extract_preferences` writes only on explicit,
confident signals ("I like/love/hate X") — never on ordinary wine chat.
Casual mentions, pairing questions, negations without a preference verb, and
statements about a third party must all be false-positive-free across a
realistic multi-turn conversation.

Exercises two layers:
1. `detect_preference_signals` directly (the pure detector).
2. `src.graph.extract_preferences_node` (the graph node), with
   `upsert_preferences` monkeypatched to a fail-fast recorder, confirming the
   "only writes on changed=True" contract holds at the node level too.
"""
from __future__ import annotations

import pytest

from src.preferences import EMPTY_PROFILE, detect_preference_signals

# ── The ordinary conversation: 12 messages that must NEVER trigger a write ───
# Includes every trap case named in the task spec, plus one RU and one DE
# ordinary query (neither language's preference verbs are implemented yet —
# see docs/PHASE3_HANDOFF.md's known multilingual gap — so these exercise the
# "no accidental match" path, not language-specific detection).
_ORDINARY_CONVERSATION: list[str] = [
    "recommend a Malbec",                                      # single-word grape mention
    "any good sweet wines?",                                    # single-word style mention
    "what pairs with sweet desserts?",                          # pairing chat
    "not too expensive",                                        # negation, no preference verb
    "my friend loves Riesling, what should she try?",           # third-person statement
    "What's the difference between Merlot and Cabernet?",       # educational query
    "How much would 6 bottles of Pinot Noir cost?",             # budget query
    "Show me wines under 20 euros",                             # filter query
    "Compare two Chardonnays for me",                           # compare query
    "What's a good wine for a dinner party?",                   # recommend query, no explicit like/hate
    "Расскажи про сорт Мальбек",                                # RU ordinary query
    "Was passt zu Lachs?",                                      # DE ordinary query
]


def test_ordinary_conversation_never_triggers_a_signal():
    """Walk the whole conversation with a fresh profile each turn (mirrors a
    user who has saved nothing yet) — every turn must return {} (no signal)."""
    for i, msg in enumerate(_ORDINARY_CONVERSATION):
        signals = detect_preference_signals(msg, dict(EMPTY_PROFILE))
        assert signals == {}, f"turn {i} ({msg!r}) unexpectedly produced a signal: {signals}"


def test_third_person_statement_does_not_match():
    """'my friend loves Riesling' contains no first-person 'I <verb>' construct,
    so the detector's _SIGNAL_VERB regex (which requires a literal 'I') never
    fires — this trap case passes without needing an xfail marker, unlike the
    task's allowance for a case the detector genuinely can't distinguish."""
    signals = detect_preference_signals(
        "my friend loves Riesling, what should she try?", dict(EMPTY_PROFILE)
    )
    assert signals == {}


def test_extract_preferences_node_never_upserts_on_ordinary_conversation(monkeypatch):
    """Same conversation, run through the real graph node with a live user_id,
    confirming upsert_preferences is never called — not just that the pure
    detector returns {}."""
    from src.graph import extract_preferences_node

    monkeypatch.setattr(
        "src.preferences.upsert_preferences",
        lambda *a, **k: pytest.fail("upsert_preferences must not be called on ordinary chat"),
    )

    profile = dict(EMPTY_PROFILE)
    for msg in _ORDINARY_CONVERSATION:
        state = {"query": msg, "profile": profile, "user_id": "u-ordinary"}
        result = extract_preferences_node(state)
        assert result["extracted_preferences"] == {}


# ── Positive controls: explicit statements DO produce a signal ──────────────


def test_explicit_like_produces_expected_preferred_type():
    signals = detect_preference_signals("I love dry reds", dict(EMPTY_PROFILE))
    assert signals != {}
    assert signals["preferred_types"] == ["Red"]


def test_explicit_dislike_produces_a_signal():
    """'sweet' isn't a real catalog style term (no style whose name contains
    it in this catalog), so per the CARDINAL RULE (src/preferences.py) it is
    recorded in free-form `notes`, not invented into disliked_styles."""
    signals = detect_preference_signals("I can't stand sweet wines", dict(EMPTY_PROFILE))
    assert signals != {}
    assert signals["disliked_styles"] == []
    assert "sweet wines" in (signals["notes"] or "")


def test_positive_controls_are_idempotent_on_second_pass():
    """Feeding the same explicit statement twice against the now-updated
    profile must not re-detect a 'new' signal the second time."""
    profile = dict(EMPTY_PROFILE)

    first = detect_preference_signals("I love dry reds", profile)
    assert first != {}
    profile = {**profile, **first}

    second = detect_preference_signals("I love dry reds", profile)
    assert second == {}


def test_extract_preferences_node_upserts_on_explicit_signal(monkeypatch):
    """Positive control for the node layer: an explicit statement DOES call
    upsert_preferences exactly once, with the detected fields."""
    from src.graph import extract_preferences_node

    calls: list[dict] = []
    monkeypatch.setattr(
        "src.preferences.upsert_preferences",
        lambda user_id, **fields: calls.append({"user_id": user_id, **fields}),
    )

    state = {"query": "I love dry reds", "profile": dict(EMPTY_PROFILE), "user_id": "u-explicit"}
    result = extract_preferences_node(state)

    assert result["extracted_preferences"] != {}
    assert len(calls) == 1
    assert calls[0]["user_id"] == "u-explicit"
    assert calls[0]["preferred_types"] == ["Red"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
