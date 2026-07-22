"""Tests for src/ui/admin.py's dev-panel model-override sentinel and the
per-user-stats login column.

Bug fixed: st.selectbox always returns a concrete option, never None. Before
this fix, _render_dev_settings defaulted the selectbox to DEFAULT_MODEL and
assigned its return value straight to st.session_state.dev_model_override —
so merely unlocking the admin panel (rendering the selectbox once, without
touching it) silently started overriding every subsequent turn's model,
regardless of the user-facing Quick/In-Depth toggle in the sidebar
(app.py: `model = st.session_state.dev_model_override or (...)`).
_resolve_model_override is the pure mapping that closes this — it's tested
directly since the surrounding function is Streamlit-bound.
"""
from __future__ import annotations

from src.ui.admin import _NO_MODEL_OVERRIDE, _resolve_model_override, _user_logins


def test_sentinel_resolves_to_none():
    """Picking (or merely defaulting to) the sentinel must mean 'no
    override' — this is what keeps opening the panel a no-op."""
    assert _resolve_model_override(_NO_MODEL_OVERRIDE) is None


def test_real_model_choice_passes_through_unchanged():
    assert _resolve_model_override("anthropic/claude-haiku-4.5") == "anthropic/claude-haiku-4.5"
    assert _resolve_model_override("openai/gpt-5.2") == "openai/gpt-5.2"


# ── _user_logins: local-part-of-email lookup for the per-user stats table ───


class _FakeUser:
    def __init__(self, id, email):
        self.id = id
        self.email = email


class _FakeAdmin:
    def __init__(self, pages):
        self._pages = pages  # list of lists of _FakeUser, one list per page
        self.calls: list[tuple] = []

    def list_users(self, page=None, per_page=None):
        self.calls.append((page, per_page))
        idx = page - 1
        return self._pages[idx] if idx < len(self._pages) else []


class _FakeDB:
    def __init__(self, pages):
        self.auth = type("A", (), {"admin": _FakeAdmin(pages)})()


def test_user_logins_returns_local_part_of_email():
    db = _FakeDB([[_FakeUser("u-1", "demo@example.com"), _FakeUser("u-2", "moonchesterjazz@gmail.com")]])

    logins = _user_logins(db)

    assert logins == {"u-1": "demo", "u-2": "moonchesterjazz"}


def test_user_logins_skips_users_with_no_email():
    db = _FakeDB([[_FakeUser("u-1", None), _FakeUser("u-2", "demo@example.com")]])

    logins = _user_logins(db)

    assert logins == {"u-2": "demo"}


def test_user_logins_paginates_until_a_short_page():
    page1 = [_FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    page2 = [_FakeUser("u-200", "last@example.com")]
    db = _FakeDB([page1, page2])

    logins = _user_logins(db)

    assert len(logins) == 201
    assert logins["u-200"] == "last"
    assert db.auth.admin.calls == [(1, 200), (2, 200)]


def test_user_logins_swallows_exceptions():
    class _BoomAdmin:
        def list_users(self, page=None, per_page=None):
            raise RuntimeError("admin API down")

    db = type("D", (), {"auth": type("A", (), {"admin": _BoomAdmin()})()})()

    assert _user_logins(db) == {}  # must not raise


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
