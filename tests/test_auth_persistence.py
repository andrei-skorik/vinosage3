"""Tests for src/auth_persistence.py — login persistence across F5 (Phase 4,
step 4/4b). Logic-level only: the real browser-side effects (cookie actually
arriving in devtools, JS execution, rotation VISIBLE across two real F5s)
are smoke-tested by a human — see the handoff for the checklist.

Step 4b redesign: reads go through the native, synchronous st.context.cookies
(monkeypatched here via a fake object with a .get()); writes/clears go
through _emit_cookie_js, captured here via monkeypatching rather than
asserting on real st.components.v1.html output. Login/register/logout/
forget-me all rerun immediately after triggering a write, so they stage via
save_token()/clear_token() (st.session_state["_pending_cookie"]) instead of
emitting inline — emit_pending_cookie(), called at the top of app.py::main(),
consumes the stage on the NEXT run. The two UI wiring call sites (logout
button in auth_view.py, "Forget everything about me" in sidebar.py) are
unchanged from step 4 — each still adds one call to clear_token() — so their
wiring is still covered by code review + the human smoke test, not repeated
here.
"""
from __future__ import annotations

import pytest
import streamlit as st

import src.auth_persistence as auth_persistence
from src.auth import AuthResult, AuthSession


class _FakeCookies:
    """Duck-typed stand-in for st.context.cookies (a Mapping)."""

    def __init__(self, cookies=None):
        self._cookies = dict(cookies or {})

    def get(self, name):
        return self._cookies.get(name)


def _reset_session_state():
    for key in ("auth", "_auth_restore_done", "_pending_cookie"):
        st.session_state.pop(key, None)


@pytest.fixture(autouse=True)
def _isolate_session_state():
    _reset_session_state()
    yield
    _reset_session_state()


def _patch_cookies(monkeypatch, cookies: dict):
    monkeypatch.setattr(st, "context", type("Ctx", (), {"cookies": _FakeCookies(cookies)})())


def _capture_emit(monkeypatch):
    calls: list[str | None] = []
    monkeypatch.setattr(auth_persistence, "_emit_cookie_js", lambda value: calls.append(value))
    return calls


# ── 1. Valid token → session restored, NEW rotated token emitted directly ───


def test_valid_token_restores_session_and_emits_rotated_token(monkeypatch):
    _patch_cookies(monkeypatch, {"vinosage_refresh_token": "old-token"})
    emit_calls = _capture_emit(monkeypatch)

    new_session = AuthSession(
        user_id="u-1", email="a@b.com",
        access_token="new-access", refresh_token="new-refresh-ROTATED",
    )
    monkeypatch.setattr(
        "src.auth.refresh_session",
        lambda token: AuthResult(ok=True, session=new_session) if token == "old-token" else None,
    )
    set_authed_calls = []
    monkeypatch.setattr(
        "src.ui.auth_view._set_authed_session",
        lambda session, *a, **k: set_authed_calls.append(session),
    )

    auth_persistence.try_restore_session()

    assert set_authed_calls == [new_session]
    # the critical assertion: the ROTATED token, not the old one, is emitted
    assert emit_calls == ["new-refresh-ROTATED"]


# ── 2. Invalid/expired token → clear emitted, no exception, stays anonymous ──


def test_invalid_token_emits_clear_and_stays_anonymous(monkeypatch):
    _patch_cookies(monkeypatch, {"vinosage_refresh_token": "garbage"})
    emit_calls = _capture_emit(monkeypatch)

    monkeypatch.setattr(
        "src.auth.refresh_session",
        lambda token: AuthResult(ok=False, error="invalid_token"),
    )
    monkeypatch.setattr(
        "src.ui.auth_view._set_authed_session",
        lambda *a, **k: pytest.fail("_set_authed_session must not be called for an invalid token"),
    )

    auth_persistence.try_restore_session()  # must not raise

    assert st.session_state.get("auth") is None
    assert emit_calls == [None]  # clear sentinel


# ── 3. No cookie → no auth calls at all (fast path) ──────────────────────────


def test_no_cookie_makes_no_auth_calls(monkeypatch):
    _patch_cookies(monkeypatch, {})
    emit_calls = _capture_emit(monkeypatch)

    monkeypatch.setattr(
        "src.auth.refresh_session",
        lambda *a, **k: pytest.fail("refresh_session must not be called when there is no cookie"),
    )
    monkeypatch.setattr(
        "src.ui.auth_view._set_authed_session",
        lambda *a, **k: pytest.fail("_set_authed_session must not be called when there is no cookie"),
    )

    auth_persistence.try_restore_session()

    assert st.session_state.get("auth") is None
    assert emit_calls == []


def test_already_authed_is_a_pure_noop(monkeypatch):
    """If st.session_state.auth is already set (e.g. mid-session login), the
    restore path must not read the cookie or touch auth at all."""
    st.session_state["auth"] = {"user_id": "u-1"}

    def _boom():
        pytest.fail("read_token must not be called when already authed")

    monkeypatch.setattr(auth_persistence, "read_token", _boom)

    auth_persistence.try_restore_session()  # must not raise


# ── 4. save_token / clear_token stage; emit_pending_cookie consumes+emits ────


def test_save_token_stages_pending_cookie_consumed_next_run(monkeypatch):
    """The login/register handler calls save_token() then st.rerun() in the
    SAME run — writing the cookie inline there would be lost (the step-4b
    bug). Staging via session_state must survive to the NEXT run, where
    emit_pending_cookie() (called at the top of app.py::main()) consumes it
    and actually emits the JS."""
    emit_calls = _capture_emit(monkeypatch)

    auth_persistence.save_token("fresh-token")
    assert emit_calls == []  # not emitted THIS run
    assert st.session_state["_pending_cookie"] == "fresh-token"

    auth_persistence.emit_pending_cookie()  # simulates the next run's top-of-main hook

    assert emit_calls == ["fresh-token"]
    assert "_pending_cookie" not in st.session_state  # consumed, not re-emitted on a 3rd call

    auth_persistence.emit_pending_cookie()
    assert emit_calls == ["fresh-token"]  # unchanged — nothing pending anymore


def test_clear_token_stages_clear_sentinel_consumed_next_run(monkeypatch):
    """Logout / forget-me: same staging mechanism, clear sentinel maps to
    _emit_cookie_js(None) (cookie deletion)."""
    emit_calls = _capture_emit(monkeypatch)

    auth_persistence.clear_token()
    assert emit_calls == []
    assert st.session_state["_pending_cookie"] == ""

    auth_persistence.emit_pending_cookie()

    assert emit_calls == [None]


def test_emit_pending_cookie_is_a_noop_when_nothing_staged(monkeypatch):
    emit_calls = _capture_emit(monkeypatch)

    auth_persistence.emit_pending_cookie()

    assert emit_calls == []


# ── _emit_cookie_js itself: validation + real HTML output ───────────────────


def test_emit_cookie_js_rejects_unsafe_characters(monkeypatch):
    html_calls = []
    monkeypatch.setattr(st.components.v1, "html", lambda html, **k: html_calls.append(html))

    auth_persistence._emit_cookie_js("has'quote")
    auth_persistence._emit_cookie_js("has;semicolon")
    auth_persistence._emit_cookie_js("has space")

    assert html_calls == []  # none rendered — all rejected


def test_emit_cookie_js_renders_set_script_with_token_and_rotation_safe_flags(monkeypatch):
    html_calls = []
    monkeypatch.setattr(st.components.v1, "html", lambda html, **k: html_calls.append(html))

    auth_persistence._emit_cookie_js("a-safe-token")

    assert len(html_calls) == 1
    js = html_calls[0]
    assert "vinosage_refresh_token=a-safe-token" in js
    assert "SameSite=Lax" in js
    assert "Max-Age=0" not in js


def test_emit_cookie_js_renders_clear_script_for_none(monkeypatch):
    html_calls = []
    monkeypatch.setattr(st.components.v1, "html", lambda html, **k: html_calls.append(html))

    auth_persistence._emit_cookie_js(None)

    assert len(html_calls) == 1
    assert "Max-Age=0" in html_calls[0]


def test_emit_cookie_js_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(
        st.components.v1, "html",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    auth_persistence._emit_cookie_js("some-token")  # must not raise


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
