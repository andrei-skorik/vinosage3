"""Tests for src/ui/session_reset.py (Phase 4, step 4c) and the forget-me
handler's wiring in src/ui/sidebar.py.

reset_to_anonymous() is exercised against the real st.session_state proxy
(works fine outside a live Streamlit app — same pattern already used in
tests/test_auth_persistence.py), seeded with representative keys to stand
in for a real logged-in session. st.rerun() is monkeypatched to a no-op /
recorder so the function can be called directly without aborting the test.
"""
from __future__ import annotations

import contextlib

import pytest
import streamlit as st

import src.ui.session_reset as session_reset


def _seed_full_session():
    st.session_state.update({
        "messages": [{"role": "user", "content": "hi"}],
        "auth": {"user_id": "u-1", "email": "a@b.com"},
        "age_confirmed": True,
        "_chat_rehydrated": True,
        "_prefs_cache": {"expertise_level": "connoisseur"},
        "_pending_profile_update": {"preferred_types": ["Red"]},
        "pref_expertise": "connoisseur",
        "pref_types": ["Red"],
        "pref_grapes": ["Malbec"],
        "pref_countries": ["Argentina"],
        "pref_styles": ["Rich & Juicy"],
        "pref_characteristics": ["Bold"],
        "disliked_types": ["White"],
        "disliked_grapes": ["Riesling"],
        "disliked_styles": ["Crisp & Zesty"],
        "pref_min_price": 10.0,
        "pref_max_price": 50.0,
        "_show_avatar_uploader": True,
        "_last_avatar_upload": ("a.png", 123),
        "avatar_uploader": object(),
        "_history_cache": [{"user_query": "old question"}],
        "wine_ratings": {"w-1": "up"},
        "_feedback_hydrated": True,
        "session_tokens_in": 500,
        "session_tokens_out": 900,
        "session_cost_micros": 1234,
        "last_latency_ms": 800,
        "_last_voice_digest": "abc123",
        "_voice_widget_gen": 3,
        "queued_prompt": "recommend a red",
        # must survive the reset — see session_reset.py's module docstring
        "_pending_cookie": "",           # a just-staged cookie-clear sentinel
        "_auth_restore_done": False,     # deliberately unset -> must be FORCED True
        "locale": "de",
        "_catalog_options_cache": {"type": ["Red", "White"]},
        "session_id": "old-session-id",
    })


@pytest.fixture(autouse=True)
def _isolate_session_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


# ── reset_to_anonymous(): clears the enumerated keys, rotates session_id ────


def test_reset_to_anonymous_clears_enumerated_keys(monkeypatch):
    monkeypatch.setattr(st, "rerun", lambda: None)
    _seed_full_session()

    session_reset.reset_to_anonymous()

    for key in session_reset._KEYS_TO_CLEAR:
        assert key not in st.session_state, f"{key!r} was not cleared"


def test_reset_to_anonymous_rotates_session_id(monkeypatch):
    monkeypatch.setattr(st, "rerun", lambda: None)
    _seed_full_session()

    session_reset.reset_to_anonymous()

    new_id = st.session_state["session_id"]
    assert new_id and new_id != "old-session-id"


def test_reset_to_anonymous_preserves_locale_and_catalog_cache(monkeypatch):
    monkeypatch.setattr(st, "rerun", lambda: None)
    _seed_full_session()

    session_reset.reset_to_anonymous()

    assert st.session_state["locale"] == "de"
    assert st.session_state["_catalog_options_cache"] == {"type": ["Red", "White"]}


def test_reset_to_anonymous_calls_rerun(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(st, "rerun", lambda: calls.append(True))
    _seed_full_session()

    session_reset.reset_to_anonymous()

    assert calls == [True]


# ── The self-defeat regressions (see module docstring for the mechanics) ────


def test_reset_to_anonymous_preserves_staged_cookie_clear(monkeypatch):
    """The logout/forget-me handler stages a cookie clear in _pending_cookie
    moments before calling reset_to_anonymous(). Wiping it here would mean
    emit_pending_cookie() never sees it on the next run, the real browser
    cookie survives, and the user auto-restores on the next F5."""
    monkeypatch.setattr(st, "rerun", lambda: None)
    _seed_full_session()
    st.session_state["_pending_cookie"] = ""

    session_reset.reset_to_anonymous()

    assert st.session_state["_pending_cookie"] == ""


def test_reset_to_anonymous_forces_auth_restore_done_true(monkeypatch):
    """Sharper trap than the cookie one: st.context.cookies reflects only
    the tab's INITIAL request and stays frozen at that value regardless of
    any document.cookie write issued via JS since. If this flag were merely
    left alone (and happened to still be False — e.g. the user logged in via
    the form this session and never went through cookie-restore),
    try_restore_session() would fire again on the very next rerun and could
    silently re-authenticate the just-erased user from that stale value —
    forget-me never calls sign_out(), so the Supabase session is still fully
    valid server-side."""
    monkeypatch.setattr(st, "rerun", lambda: None)
    _seed_full_session()
    st.session_state["_auth_restore_done"] = False

    session_reset.reset_to_anonymous()

    assert st.session_state["_auth_restore_done"] is True


# ── Forget-me handler wiring (src/ui/sidebar.py) ─────────────────────────────


def test_forget_me_handler_calls_all_deletions_then_reset_last(monkeypatch):
    """Heavy widget stubbing is required here because render_taste_profile()
    is one straight-line function with no seams — every st.* call it makes
    before reaching the forget-me popover must be stubbed to drive execution
    down to the "yes" branch. Order is asserted only for reset_to_anonymous
    being last, per the task's own scoping ("order not gated except reset
    last")."""
    import src.ui.sidebar as sidebar

    calls: list[str] = []

    st.session_state["auth"] = {"user_id": "u-1", "access_token": "at", "refresh_token": "rt"}
    st.session_state["_prefs_cache"] = dict(sidebar.EMPTY_PROFILE)

    monkeypatch.setattr(sidebar, "_catalog_options", lambda: {
        "type": [], "grape": [], "country": [], "style": [], "characteristics": [],
    })
    monkeypatch.setattr(st, "expander", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(st, "popover", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(st, "spinner", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "radio", lambda *a, **k: "beginner")
    monkeypatch.setattr(st, "multiselect", lambda *a, **k: [])
    monkeypatch.setattr(st, "number_input", lambda *a, **k: 0.0)
    monkeypatch.setattr(st, "success", lambda *a, **k: None)
    monkeypatch.setattr(st, "error", lambda *a, **k: None)
    monkeypatch.setattr(st, "button", lambda *a, **k: False)  # save_profile_btn -> not taken

    class _FakeCol:
        def __init__(self, clicked: bool):
            self._clicked = clicked

        def button(self, *a, **k):
            return self._clicked

    monkeypatch.setattr(st, "columns", lambda *a, **k: (_FakeCol(True), _FakeCol(False)))

    monkeypatch.setattr(
        sidebar, "delete_preferences",
        lambda uid: calls.append(f"delete_preferences:{uid}") or True,
    )
    monkeypatch.setattr(
        "src.graph.delete_thread",
        lambda tid: calls.append(f"delete_thread:{tid}") or True,
    )
    monkeypatch.setattr(
        "src.logging_db.delete_all_feedback",
        lambda uid: calls.append(f"delete_all_feedback:{uid}"),
    )
    monkeypatch.setattr(
        "src.logging_db.erase_user_history",
        lambda uid: calls.append(f"erase_user_history:{uid}") or True,
    )
    monkeypatch.setattr(
        "src.auth_persistence.clear_token",
        lambda: calls.append("clear_token"),
    )
    monkeypatch.setattr(
        "src.ui.session_reset.reset_to_anonymous",
        lambda: calls.append("reset_to_anonymous"),
    )

    sidebar.render_taste_profile("en")

    assert calls[-1] == "reset_to_anonymous"
    assert set(calls[:-1]) == {
        "delete_preferences:u-1",
        "delete_thread:user:u-1",
        "delete_all_feedback:u-1",
        "erase_user_history:u-1",
        "clear_token",
    }


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
