"""Tests for src/auth.py::delete_account and its wiring in
src/ui/auth_view.py::render_profile_widget's "Delete My Account" button.

Deliberately NOT built on "Forget everything about me" (src/ui/sidebar.py) —
that erases app-data only and never touches the Supabase Auth account
(docs/PHASE3_HANDOFF.md Backlog #18). delete_account ends the account
itself; the only thing it reuses from the forget-me code is
erase_user_history, needed as a hard technical prerequisite (query_logs.user_id
has no ON DELETE clause, so the account delete would hit a foreign-key
violation unless that column is nulled out first) — not a dependency on the
forget-me feature/button.

Placement (human-requested revision): the button lives INSIDE the
expandable avatar-upload panel (behind the pencil icon), not on its own
sidebar row — so its label never has to share space with "Log Out". All
tests here therefore pre-set `_show_avatar_uploader = True` to reach it.
"""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

from src.auth import delete_account


# ── delete_account: the pure Admin API + FK-prerequisite logic ──────────────


def test_delete_account_erases_history_before_deleting_the_user():
    calls: list[str] = []
    mock_admin = MagicMock()
    mock_admin.delete_user.side_effect = lambda uid: calls.append(f"delete_user:{uid}")
    mock_db = MagicMock()
    mock_db.auth.admin = mock_admin

    with patch("src.catalog.get_service_db", return_value=mock_db), \
         patch("src.logging_db.erase_user_history", side_effect=lambda uid: calls.append(f"erase_user_history:{uid}") or True):
        result = delete_account("user-1")

    assert result is True
    assert calls == ["erase_user_history:user-1", "delete_user:user-1"]


def test_delete_account_swallows_exceptions_returns_false():
    with patch("src.catalog.get_service_db", side_effect=RuntimeError("db down")):
        result = delete_account("user-1")  # must not raise

    assert result is False


def test_delete_account_returns_false_if_admin_delete_fails():
    mock_admin = MagicMock()
    mock_admin.delete_user.side_effect = RuntimeError("admin API down")
    mock_db = MagicMock()
    mock_db.auth.admin = mock_admin

    with patch("src.catalog.get_service_db", return_value=mock_db), \
         patch("src.logging_db.erase_user_history", return_value=True):
        result = delete_account("user-1")  # must not raise

    assert result is False


# ── render_profile_widget wiring: the "Delete My Account" confirm flow ──────


class _FakeCol:
    def __init__(self, clicked: bool):
        self._clicked = clicked

    def button(self, *a, **k):
        return self._clicked


@pytest.fixture(autouse=True)
def _isolate_session_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


def _stub_common_widgets(monkeypatch, *, yes_clicked: bool = False, cancel_clicked: bool = False):
    """Stubs every st.* call render_profile_widget makes on the way to (and
    around) the delete-account popover, which now lives inside the
    expandable avatar panel. st.columns is called at most twice, in order:
    (avatar row: 3 cols, never need a real .button()), then — only because
    _show_avatar_uploader is pre-set True by every caller — (popover's
    yes/cancel: 2 cols, the only ones that need one)."""
    st.session_state["_show_avatar_uploader"] = True

    monkeypatch.setattr(st, "image", lambda *a, **k: None)
    monkeypatch.setattr(st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "divider", lambda *a, **k: None)
    monkeypatch.setattr(st, "button", lambda *a, **k: False)  # "✏️" and "🚪" — not clicked
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: None)  # no file selected
    monkeypatch.setattr(st, "popover", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(st, "success", lambda *a, **k: None)
    monkeypatch.setattr(st, "error", lambda *a, **k: None)
    monkeypatch.setattr(st, "rerun", lambda: None)

    columns_calls = {"n": 0}

    def _fake_columns(*a, **k):
        columns_calls["n"] += 1
        if columns_calls["n"] == 1:
            return (contextlib.nullcontext(), contextlib.nullcontext(), contextlib.nullcontext())
        return (_FakeCol(yes_clicked), _FakeCol(cancel_clicked))

    monkeypatch.setattr(st, "columns", _fake_columns)


def test_delete_account_confirm_click_deletes_thread_clears_cookie_and_resets(monkeypatch):
    import src.ui.auth_view as auth_view

    calls: list[str] = []
    _stub_common_widgets(monkeypatch, yes_clicked=True)

    st.session_state["auth"] = {"user_id": "u-1", "email": "a@b.com", "access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(auth_view, "delete_account", lambda uid: calls.append(f"delete_account:{uid}") or True)
    monkeypatch.setattr("src.graph.delete_thread", lambda tid: calls.append(f"delete_thread:{tid}") or True)
    monkeypatch.setattr(auth_view, "clear_token", lambda: calls.append("clear_token"))
    monkeypatch.setattr("src.ui.session_reset.reset_to_anonymous", lambda: calls.append("reset_to_anonymous"))

    auth_view.render_profile_widget("en")

    assert calls == [
        "delete_account:u-1", "delete_thread:user:u-1", "clear_token", "reset_to_anonymous",
    ]


def test_delete_account_no_click_does_nothing(monkeypatch):
    import src.ui.auth_view as auth_view

    calls: list[str] = []
    _stub_common_widgets(monkeypatch)

    st.session_state["auth"] = {"user_id": "u-1", "email": "a@b.com", "access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(
        auth_view, "delete_account",
        lambda uid: pytest.fail("delete_account must not be called without confirmation"),
    )
    monkeypatch.setattr(
        "src.graph.delete_thread",
        lambda tid: pytest.fail("delete_thread must not be called without confirmation"),
    )

    auth_view.render_profile_widget("en")  # must not raise / must not delete anything

    assert calls == []


def test_delete_account_not_reachable_when_avatar_panel_closed(monkeypatch):
    """The popover lives INSIDE the expandable avatar panel — with it
    collapsed (the default), the delete-account flow must not run at all,
    even if some stray session_state left the confirm button "clicked"."""
    import src.ui.auth_view as auth_view

    _stub_common_widgets(monkeypatch, yes_clicked=True)
    st.session_state["_show_avatar_uploader"] = False  # override the fixture's default

    st.session_state["auth"] = {"user_id": "u-1", "email": "a@b.com", "access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(
        auth_view, "delete_account",
        lambda uid: pytest.fail("delete_account must not run while the avatar panel is collapsed"),
    )

    auth_view.render_profile_widget("en")  # must not raise / must not delete anything


def test_delete_account_failure_shows_error_and_does_not_reset(monkeypatch):
    import src.ui.auth_view as auth_view

    calls: list[str] = []
    _stub_common_widgets(monkeypatch, yes_clicked=True)
    error_calls: list = []
    monkeypatch.setattr(st, "error", lambda *a, **k: error_calls.append(a))

    st.session_state["auth"] = {"user_id": "u-1", "email": "a@b.com", "access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(auth_view, "delete_account", lambda uid: False)
    monkeypatch.setattr(
        "src.graph.delete_thread",
        lambda tid: pytest.fail("delete_thread must not run when the account delete itself failed"),
    )
    monkeypatch.setattr(
        "src.ui.session_reset.reset_to_anonymous",
        lambda: pytest.fail("reset_to_anonymous must not run when the account delete itself failed"),
    )

    auth_view.render_profile_widget("en")

    assert len(error_calls) == 1


def test_cancel_click_rotates_popover_key_and_reruns(monkeypatch):
    """st.popover has no programmatic close, and a button click INSIDE it
    (Cancel) doesn't dismiss it — only clicking outside does. Mounting the
    popover under a rotated key on the next rerun is the workaround (same
    trick as the voice recorder's _voice_widget_gen); confirm Cancel actually
    bumps the counter and asks for a rerun."""
    import src.ui.auth_view as auth_view

    _stub_common_widgets(monkeypatch, cancel_clicked=True)
    rerun_calls: list = []
    monkeypatch.setattr(st, "rerun", lambda: rerun_calls.append(True))

    st.session_state["auth"] = {"user_id": "u-1", "email": "a@b.com", "access_token": "at", "refresh_token": "rt"}
    assert "_delete_popover_gen" not in st.session_state

    auth_view.render_profile_widget("en")

    assert st.session_state["_delete_popover_gen"] == 1
    assert rerun_calls == [True]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
