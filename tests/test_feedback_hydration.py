"""Tests for the feedback-hydration fix
(docs/phase3.1/fix_feedback_hydration/).

Bug: after logout->login (profile intact, NOT forget-me) or a plain F5,
rehydrated chat history rendered every feedback button grey even though
recommendation_feedback still held the ratings — the session-state ratings
cache is only ever populated by a click in the CURRENT session, and a fresh
session starts with none. `_hydrate_feedback_ratings` (extracted from
render_feedback_buttons, same rationale as `_toggle_feedback`) back-fills
it from the DB exactly once per session, keyed by (query_id, wine_id)
throughout — never wine_id alone, which was the cross-turn highlight leak
fixed just before this.

render_feedback_buttons itself is Streamlit-bound and not exercised
directly here, per the task's own scoping (highlight is invisible to
mocks) — these tests pin the pure state layer.
"""
from __future__ import annotations

import pytest
import streamlit as st

from src.ui import chat_view


@pytest.fixture(autouse=True)
def _isolate_session_state():
    st.session_state.pop("_feedback_hydrated", None)
    st.session_state.pop("messages", None)
    yield
    st.session_state.pop("_feedback_hydrated", None)
    st.session_state.pop("messages", None)


def _seed_messages(*query_ids: str) -> None:
    """Stand-in for a rehydrated chat_log: one assistant turn per query_id."""
    st.session_state["messages"] = [
        {"role": "assistant", "content": "...", "query_id": qid} for qid in query_ids
    ]


# ── 1. Back-fill populates the right (query_id, wine_id) pairs ──────────────


def test_hydrate_populates_ratings_for_every_turn_in_history(monkeypatch):
    _seed_messages("q1", "q2")
    monkeypatch.setattr(
        "src.logging_db.get_feedback_ratings",
        lambda user_id, query_ids: {("q1", "w-1"): "up", ("q2", "w-1"): "down"},
    )

    ratings: dict = {}
    chat_view._hydrate_feedback_ratings("u-1", ratings)

    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"
    assert ratings[chat_view._rating_key("q2", "w-1")] == "down"
    assert st.session_state["_feedback_hydrated"] is True


def test_hydrate_passes_every_query_id_from_history_to_the_db_call(monkeypatch):
    _seed_messages("q1", "q2", "q3")
    seen: dict = {}

    def _fake(user_id, query_ids):
        seen["user_id"] = user_id
        seen["query_ids"] = query_ids
        return {}

    monkeypatch.setattr("src.logging_db.get_feedback_ratings", _fake)

    chat_view._hydrate_feedback_ratings("u-1", {})

    assert seen["user_id"] == "u-1"
    assert seen["query_ids"] == ["q1", "q2", "q3"]


# ── 2. Runs once — a second call (this session) is a no-op ──────────────────


def test_hydrate_runs_only_once_per_session(monkeypatch):
    _seed_messages("q1")
    calls: list = []
    monkeypatch.setattr(
        "src.logging_db.get_feedback_ratings",
        lambda user_id, query_ids: calls.append(1) or {("q1", "w-1"): "up"},
    )

    ratings: dict = {}
    chat_view._hydrate_feedback_ratings("u-1", ratings)
    assert len(calls) == 1

    # A second card rendering in the same (or a later) rerun must not hit
    # the DB again.
    chat_view._hydrate_feedback_ratings("u-1", ratings)
    assert len(calls) == 1


def test_hydrate_is_a_noop_when_flag_already_set(monkeypatch):
    st.session_state["_feedback_hydrated"] = True

    def _boom(*a, **k):
        pytest.fail("get_feedback_ratings must not be called when already hydrated")

    monkeypatch.setattr("src.logging_db.get_feedback_ratings", _boom)

    chat_view._hydrate_feedback_ratings("u-1", {})  # must not raise


# ── 3. Cross-turn independence still holds after hydration (regression) ─────


def test_hydrated_ratings_keep_same_wine_different_turns_independent(monkeypatch):
    """Regression guard for the highlight-leak fix: a wine rated differently
    in two turns must hydrate as two independent entries, not collapse into
    one shared wine_id-only rating."""
    _seed_messages("q1", "q2")
    monkeypatch.setattr(
        "src.logging_db.get_feedback_ratings",
        lambda user_id, query_ids: {("q1", "w-1"): "up", ("q2", "w-1"): "down"},
    )

    ratings: dict = {}
    chat_view._hydrate_feedback_ratings("u-1", ratings)

    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"
    assert ratings[chat_view._rating_key("q2", "w-1")] == "down"
    assert ratings[chat_view._rating_key("q1", "w-1")] != ratings[chat_view._rating_key("q2", "w-1")]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
