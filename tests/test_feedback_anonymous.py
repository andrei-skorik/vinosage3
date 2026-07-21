"""Tests for the feedback-persistence guard (Phase 3 / v3.0, step 6 + 6b).

SPEC invariant (Appendix B) / CLAUDE.md: anonymous users never write
preferences/feedback to the DB. `chat_view._toggle_feedback` (extracted from
`render_feedback_buttons`'s `_toggle` closure for testability — pure
refactor, zero behavior change; see its docstring) is the single call site
that decides whether a rating gets persisted, so it is exercised directly
here without a Streamlit runtime.

History: step 6 found that `log_feedback` was called unconditionally (only
`fold_feedback`/`delete_feedback` were gated on `user_id`), so an anonymous
rating still inserted a `user_id=NULL` row into `recommendation_feedback`.
That assertion was marked `xfail(strict=True)` rather than silently patched
or weakened, pending a human decision (documented in step 6's report).

Step 6b resolution (human decision, variant b): the invariant stands as
written. `log_feedback` is now also gated on `user_id` in
`_toggle_feedback`, and `render_feedback_buttons` hides the buttons entirely
for anonymous users (showing `feedback_login_hint` instead) as a second,
independent layer. Rationale: `recommendation_feedback`'s
`unique(user_id, query_id, wine_id)` constraint can't deduplicate NULL-user
rows (Postgres NULL != NULL), so anonymous re-taps would have inserted
duplicates and skewed the admin feedback-insights analytics (step 5, №2/№4).
Anonymous analytics via session_id-based dedup is a deliberate backlog item,
not attempted here. The xfail is gone — this now passes for real.
"""
from __future__ import annotations

import pytest

from src.ui import chat_view


def _make_wine(wine_id: str = "w-1") -> dict:
    return {
        "wine_id": wine_id, "title": "Test Wine",
        "type": "Red", "grape": "Malbec", "style": "Bold & Spicy",
    }


@pytest.fixture(autouse=True)
def _stub_toast(monkeypatch):
    """Avoid noisy 'missing ScriptRunContext' warnings from st.toast()
    when _toggle_feedback runs outside a real Streamlit app."""
    monkeypatch.setattr(chat_view.st, "toast", lambda *a, **k: None)


# ── Anonymous: zero DB writes through any path (mandatory assertion) ────────


def test_anonymous_never_calls_log_feedback_or_fold_feedback(monkeypatch):
    monkeypatch.setattr(
        "src.logging_db.log_feedback",
        lambda **k: pytest.fail("log_feedback must never be called for an anonymous user"),
    )
    monkeypatch.setattr(
        "src.preferences.fold_feedback",
        lambda *a, **k: pytest.fail("fold_feedback must never be called for an anonymous user"),
    )
    ratings: dict = {}
    chat_view._toggle_feedback(
        _make_wine(), "up",
        ratings=ratings, user_id=None, session_id="s1", query_id="q1", locale="en",
    )
    # The button state still updates locally (session-only) — only the DB
    # writes are gated.
    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"


def test_anonymous_toggle_off_never_calls_delete_or_fold(monkeypatch):
    monkeypatch.setattr(
        "src.preferences.fold_feedback",
        lambda *a, **k: pytest.fail("fold_feedback must never be called for an anonymous user"),
    )
    monkeypatch.setattr(
        "src.logging_db.delete_feedback",
        lambda **k: pytest.fail("delete_feedback must never be called for an anonymous user"),
    )
    ratings = {chat_view._rating_key("q1", "w-1"): "down"}  # already rated -> this call toggles it off
    chat_view._toggle_feedback(
        _make_wine(), "down",
        ratings=ratings, user_id=None, session_id="s1", query_id="q1", locale="en",
    )
    assert ratings[chat_view._rating_key("q1", "w-1")] is None


# ── Positive control: logged-in users DO persist through both paths ─────────


def test_authenticated_user_calls_log_feedback_and_fold_feedback(monkeypatch):
    """No prior rating -> no reason lookup needed; fold_feedback is called
    for the new rating and its returned delta is recorded via log_feedback's
    reason (Phase 3 step 6h)."""
    calls: dict = {"log": None, "fold": None}

    def _log(**kwargs):
        calls["log"] = kwargs
        return True

    def _fold(user_id, wine, rating, *, delta=None):
        calls["fold"] = (user_id, wine, rating, delta)
        return {"preferred_types": ["Red"]}, {"added_preferred_types": ["Red"]}

    monkeypatch.setattr("src.logging_db.log_feedback", _log)
    monkeypatch.setattr("src.preferences.fold_feedback", _fold)

    wine = _make_wine()
    ratings: dict = {}
    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="user-42", session_id="s1", query_id="q1", locale="en",
    )

    assert calls["log"] is not None
    assert calls["log"]["user_id"] == "user-42"
    assert calls["log"]["rating"] == "up"
    assert calls["log"]["wine_id"] == "w-1"
    assert calls["log"]["reason"] == '{"added_preferred_types": ["Red"]}'
    assert calls["fold"] == ("user-42", wine, "up", None)
    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"


def test_authenticated_toggle_off_calls_delete_and_fold_none(monkeypatch):
    """Toggle-off reads the row's recorded delta and reverts exactly that
    (Phase 3 step 6h) — never a blanket removal — then deletes the row."""
    calls: dict = {"delete": None, "fold": None}
    recorded_delta = {"added_disliked_styles": ["Ripe & Rounded"]}

    def _delete(**kwargs):
        calls["delete"] = kwargs

    def _fold(user_id, wine, rating, *, delta=None):
        calls["fold"] = (user_id, wine, rating, delta)
        return None, {}

    monkeypatch.setattr("src.logging_db.delete_feedback", _delete)
    monkeypatch.setattr("src.logging_db.get_feedback_reason", lambda **k: recorded_delta)
    monkeypatch.setattr("src.preferences.fold_feedback", _fold)

    wine = _make_wine()
    ratings = {chat_view._rating_key("q1", "w-1"): "up"}
    chat_view._toggle_feedback(
        wine, "up",
        ratings=ratings, user_id="user-42", session_id="s1", query_id="q1", locale="en",
    )

    assert ratings[chat_view._rating_key("q1", "w-1")] is None
    assert calls["delete"] == {"user_id": "user-42", "wine_id": "w-1"}
    assert calls["fold"] == ("user-42", wine, "none", recorded_delta)


# ── UI layer: anonymous users see no buttons at all (step 6b, edit 1b) ──────


def test_render_feedback_buttons_shows_hint_not_buttons_for_anonymous(monkeypatch):
    """render_feedback_buttons must render zero st.button calls for an
    anonymous session and show the login hint caption instead."""
    import streamlit as st

    button_calls: list = []
    caption_calls: list = []
    monkeypatch.setattr(st, "button", lambda *a, **k: button_calls.append((a, k)) or False)
    monkeypatch.setattr(st, "caption", lambda *a, **k: caption_calls.append((a, k)))
    monkeypatch.setattr(st.session_state, "get", lambda key, default=None: (
        "s1" if key == "session_id" else None if key == "auth" else default
    ))

    tool_calls = [{
        "tool_name": "recommend_for_me",
        "result": {"recommendations": [
            {"wine_id": "w-1", "title": "Test Wine", "type": "Red", "grape": "Malbec", "style": "Bold"}
        ]},
    }]
    chat_view.render_feedback_buttons(tool_calls, query_id="q1", locale="en", response_text="Test Wine")

    assert button_calls == []
    assert len(caption_calls) == 1
    assert caption_calls[0][0][0] == "Log in to rate recommendations."


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
