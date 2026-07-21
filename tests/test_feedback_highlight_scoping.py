"""Tests for the feedback-highlight cross-turn leak fix
(docs/phase3.1/fix_feedback_highlight_leak/).

Root cause: render_feedback_buttons's ACTIVE-STATE read (which button style
to render) and _toggle_feedback's read/write into the `ratings` cache were
keyed by wine_id alone, even though the DB write path
(log_feedback/delete_feedback/get_feedback_reason) and the button/container
widget keys were already correctly scoped by (query_id, wine_id). Result:
rating a wine in one turn visually "leaked" its colour onto every other
turn's card for that same wine — most visibly when recommend_for_me
re-suggests the same wines across turns.

render_feedback_buttons itself is Streamlit-bound and not exercised
directly here (per the task's own scoping) — these tests pin the pure
state layer: _rating_key() and _toggle_feedback()'s use of it.
"""
from __future__ import annotations

import pytest

from src.ui import chat_view


def _make_wine(wine_id: str = "w-1") -> dict:
    return {
        "wine_id": wine_id, "title": "Test Wine",
        "type": "Red", "grape": "Assyrtiko", "style": "Crisp & Zesty",
    }


@pytest.fixture(autouse=True)
def _stub_toast(monkeypatch):
    """Avoid noisy 'missing ScriptRunContext' warnings from st.toast()
    when _toggle_feedback runs outside a real Streamlit app."""
    monkeypatch.setattr(chat_view.st, "toast", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _stub_feedback_db(monkeypatch):
    """The DB write path (already correctly (query_id, wine_id)-scoped) is
    not the subject of this fix — stub it to a no-op so _toggle_feedback
    exercises only the ratings-dict/state layer under test."""
    monkeypatch.setattr("src.logging_db.log_feedback", lambda **k: True)
    monkeypatch.setattr("src.logging_db.delete_feedback", lambda **k: None)
    monkeypatch.setattr("src.logging_db.get_feedback_reason", lambda **k: None)
    monkeypatch.setattr("src.preferences.fold_feedback", lambda *a, **k: (None, {}))


# ── _rating_key: the composite identity a card's state is scoped by ─────────


def test_rating_key_differs_across_query_ids_for_the_same_wine():
    assert chat_view._rating_key("q1", "w-1") != chat_view._rating_key("q2", "w-1")


def test_rating_key_is_stable_for_the_same_query_and_wine():
    assert chat_view._rating_key("q1", "w-1") == chat_view._rating_key("q1", "w-1")


# ── 1. Same wine, two different turns: rating one leaves the other unrated ──


def test_rating_on_one_query_id_leaves_a_sibling_query_id_unrated(monkeypatch):
    ratings: dict = {}
    wine = _make_wine("w-1")

    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q1", locale="en",
    )

    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"
    # the exact leak this task fixes: a DIFFERENT turn's card for the SAME
    # wine must read as unrated, not "up"
    assert ratings.get(chat_view._rating_key("q2", "w-1")) is None


# ── 2. Toggling one turn's rating must not alter a sibling turn's ───────────


def test_toggling_one_query_id_does_not_alter_a_sibling_query_id(monkeypatch):
    ratings: dict = {}
    wine = _make_wine("w-1")

    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q1", locale="en",
    )
    chat_view._toggle_feedback(
        wine, "down",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q2", locale="en",
    )

    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"
    assert ratings[chat_view._rating_key("q2", "w-1")] == "down"

    # toggling q1's rating off must not touch q2's independent state
    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q1", locale="en",
    )
    assert ratings[chat_view._rating_key("q1", "w-1")] is None
    assert ratings[chat_view._rating_key("q2", "w-1")] == "down"


# ── 3. Composite key round-trips the correct turn's rating ──────────────────


def test_composite_key_roundtrips_the_correct_turns_rating(monkeypatch):
    ratings: dict = {}
    wine = _make_wine("w-1")

    chat_view._toggle_feedback(
        wine, "down",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q1", locale="en",
    )
    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="u-1", session_id="s1", query_id="q2", locale="en",
    )

    # write then read returns exactly what was written for THAT query_id,
    # never a sibling turn's value
    assert ratings[chat_view._rating_key("q1", "w-1")] == "down"
    assert ratings[chat_view._rating_key("q2", "w-1")] == "up"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
