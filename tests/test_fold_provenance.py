"""Tests for delta-provenance un-fold (Phase 3, step 6h).

Bug (inherited from Phase 2, found in the human's smoke test): toggle-off
removed a wine's grape/style/type from BOTH preferred_* and disliked_*
unconditionally — but the fold itself (guarded per SPEC §5.4 by step 6f) may
have added NOTHING (e.g. a 👎 on a wine whose grape+style were already
manually preferred). Un-fold must revert exactly what fold did, never more.

Design: each applied fold's delta (what it actually added/removed) is
serialized into recommendation_feedback.reason (sql/08, previously unused —
no schema change) on the same row write. A later toggle-off (or rating
flip) reads that delta back and reverts EXACTLY it, before the row is
deleted (toggle-off) or the new rating's fold is applied (flip). Missing/
legacy/unparseable reason -> revert NOTHING (safe default).

These tests exercise the full flow through `chat_view._toggle_feedback`
against small in-memory fakes for the two tables involved
(user_preferences via src.preferences.get_service_db, recommendation_feedback
via src.logging_db._db) — real fold_feedback / log_feedback / delete_feedback
/ get_feedback_reason code runs, only the DB client is faked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.ui import chat_view

_EMPTY_PROFILE = {
    "user_id": "u1",
    "expertise_level": "beginner",
    "preferred_types": [], "preferred_grapes": [], "preferred_countries": [],
    "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
    "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
}


class _FakeProfileDB:
    """Stateful fake for get_service_db() as used by fold_feedback /
    upsert_preferences against the user_preferences table."""

    def __init__(self, profile: dict):
        self.profile = dict(profile)

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, row, *_a, **_k):
        self.profile.update(row)
        return self

    def execute(self):
        resp = MagicMock()
        resp.data = [dict(self.profile)]
        return resp


class _FakeFeedbackDB:
    """Stateful in-memory fake for recommendation_feedback, as used by
    log_feedback / get_feedback_reason / delete_feedback, keyed by
    (user_id, query_id, wine_id)."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self._op: str | None = None
        self._filters: dict = {}
        self._payload: dict | None = None

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        self._op = "select"
        self._filters = {}
        return self

    def upsert(self, row, on_conflict=None, **_k):
        self._op = "write"
        self._payload = row
        return self

    def insert(self, row, **_k):
        self._op = "write"
        self._payload = row
        return self

    def delete(self, *_a, **_k):
        self._op = "delete"
        self._filters = {}
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        resp = MagicMock()
        if self._op == "select":
            key = (self._filters.get("user_id"), self._filters.get("query_id"), self._filters.get("wine_id"))
            row = self.rows.get(key)
            resp.data = [row] if row else []
        elif self._op == "write":
            row = self._payload
            key = (row.get("user_id"), row.get("query_id"), row.get("wine_id"))
            self.rows[key] = dict(row)
            resp.data = [dict(row)]
        elif self._op == "delete":
            uid, wid = self._filters.get("user_id"), self._filters.get("wine_id")
            for k in [k for k in self.rows if k[0] == uid and k[2] == wid]:
                del self.rows[k]
            resp.data = []
        return resp


def _toggle(wine, direction, ratings, *, profile_db, feedback_db, monkeypatch,
            user_id="u1", session_id="s1", query_id="q1", locale="en"):
    monkeypatch.setattr("src.preferences.get_service_db", lambda: profile_db)
    monkeypatch.setattr("src.logging_db._db", lambda: feedback_db)
    monkeypatch.setattr(chat_view.st, "toast", lambda *a, **k: None)
    chat_view._toggle_feedback(
        wine, direction,
        ratings=ratings, user_id=user_id, session_id=session_id,
        query_id=query_id, locale=locale,
    )


def _lists(profile: dict) -> dict:
    fields = (
        "preferred_types", "preferred_grapes", "preferred_styles",
        "disliked_types", "disliked_grapes", "disliked_styles",
    )
    return {f: sorted(profile.get(f) or []) for f in fields}


# ── 1. THE INCIDENT: fold adds nothing -> toggle-off touches nothing ────────


def test_incident_down_vote_on_fully_preferred_wine_then_toggle_off(monkeypatch):
    profile = {**_EMPTY_PROFILE, "preferred_grapes": ["Assyrtiko"], "preferred_styles": ["Crisp & Zesty"]}
    profile_db = _FakeProfileDB(profile)
    feedback_db = _FakeFeedbackDB()
    wine = {"wine_id": "w-1", "type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    ratings: dict = {}

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    row = feedback_db.rows[("u1", "q1", "w-1")]
    assert json.loads(row["reason"]) == {}
    assert _lists(profile_db.profile) == {
        "preferred_types": [], "preferred_grapes": ["Assyrtiko"], "preferred_styles": ["Crisp & Zesty"],
        "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    }

    # Toggle off.
    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    assert ("u1", "q1", "w-1") not in feedback_db.rows
    assert _lists(profile_db.profile) == {
        "preferred_types": [], "preferred_grapes": ["Assyrtiko"], "preferred_styles": ["Crisp & Zesty"],
        "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    }


# ── 2. Non-preferred style folds normally, toggle-off reverts just that ────


def test_down_vote_with_partial_overlap_then_toggle_off(monkeypatch):
    profile = {**_EMPTY_PROFILE, "preferred_grapes": ["Assyrtiko"]}
    profile_db = _FakeProfileDB(profile)
    feedback_db = _FakeFeedbackDB()
    wine = {"wine_id": "w-1", "type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    ratings: dict = {}

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    row = feedback_db.rows[("u1", "q1", "w-1")]
    assert json.loads(row["reason"]) == {"added_disliked_styles": ["Crisp & Zesty"]}
    assert _lists(profile_db.profile)["disliked_styles"] == ["Crisp & Zesty"]
    assert _lists(profile_db.profile)["preferred_grapes"] == ["Assyrtiko"]

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    assert ("u1", "q1", "w-1") not in feedback_db.rows
    assert _lists(profile_db.profile) == {
        "preferred_types": [], "preferred_grapes": ["Assyrtiko"], "preferred_styles": [],
        "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    }


# ── 3. Manual dislike + a no-op fold on the same value -> untouched by revert


def test_manual_dislike_survives_toggle_off_of_a_noop_fold(monkeypatch):
    profile = {**_EMPTY_PROFILE, "disliked_grapes": ["Malbec"]}
    profile_db = _FakeProfileDB(profile)
    feedback_db = _FakeFeedbackDB()
    wine = {"wine_id": "w-1", "type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    ratings: dict = {}

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    row = feedback_db.rows[("u1", "q1", "w-1")]
    delta = json.loads(row["reason"])
    # Malbec was already disliked -> the fold recorded no addition for grapes.
    assert "added_disliked_grapes" not in delta
    assert delta.get("added_disliked_styles") == ["Rich & Juicy"]

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    # The manual dislike survives; only the fold's own addition is reverted.
    assert _lists(profile_db.profile)["disliked_grapes"] == ["Malbec"]
    assert _lists(profile_db.profile)["disliked_styles"] == []


# ── 4. Rating flip: outgoing delta reverted, new fold applied + recorded ───


def test_flip_down_to_up_reverts_down_delta_and_applies_up(monkeypatch):
    profile_db = _FakeProfileDB(dict(_EMPTY_PROFILE))
    feedback_db = _FakeFeedbackDB()
    wine = {"wine_id": "w-1", "type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    ratings: dict = {}

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)
    assert _lists(profile_db.profile)["disliked_grapes"] == ["Malbec"]
    assert _lists(profile_db.profile)["disliked_styles"] == ["Rich & Juicy"]
    assert ratings[chat_view._rating_key("q1", "w-1")] == "down"

    _toggle(wine, "up", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    assert ratings[chat_view._rating_key("q1", "w-1")] == "up"
    final = _lists(profile_db.profile)
    assert final["disliked_grapes"] == []
    assert final["disliked_styles"] == []
    assert final["preferred_types"] == ["Red"]
    assert final["preferred_grapes"] == ["Malbec"]
    assert final["preferred_styles"] == ["Rich & Juicy"]

    row = feedback_db.rows[("u1", "q1", "w-1")]
    assert row["rating"] == "up"
    up_delta = json.loads(row["reason"])
    assert up_delta.get("added_preferred_types") == ["Red"]
    assert up_delta.get("added_preferred_grapes") == ["Malbec"]
    assert up_delta.get("added_preferred_styles") == ["Rich & Juicy"]
    # The down fold's additions must not still be attributed to this (new) row.
    assert "added_disliked_grapes" not in up_delta
    assert "added_disliked_styles" not in up_delta


# ── 5. Legacy row (reason NULL): revert nothing, still delete the row ──────


def test_legacy_row_with_null_reason_reverts_nothing(monkeypatch):
    profile = {**_EMPTY_PROFILE, "preferred_grapes": ["Malbec"], "disliked_styles": ["Something Else"]}
    profile_db = _FakeProfileDB(profile)
    feedback_db = _FakeFeedbackDB()
    # Pre-seed a legacy row predating step 6h: rating recorded, reason NULL.
    feedback_db.rows[("u1", "q1", "w-1")] = {
        "session_id": "s1", "user_id": "u1", "query_id": "q1", "wine_id": "w-1",
        "wine_title": "Old Wine", "rating": "down", "reason": None,
    }
    wine = {"wine_id": "w-1", "type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    ratings = {chat_view._rating_key("q1", "w-1"): "down"}

    _toggle(wine, "down", ratings, profile_db=profile_db, feedback_db=feedback_db, monkeypatch=monkeypatch)

    assert ("u1", "q1", "w-1") not in feedback_db.rows  # row still deleted
    # Nothing reverted: profile identical to before the toggle-off.
    assert _lists(profile_db.profile) == _lists(profile)


# ── 6. Sidebar-cache parity on the incident + partial-overlap cases ────────


def test_sidebar_cache_parity_on_incident_and_partial_overlap():
    from src.ui.chat_view import _fold_profile_dict

    # Case 1 (the incident): fold adds nothing.
    profile1 = {**_EMPTY_PROFILE, "preferred_grapes": ["Assyrtiko"], "preferred_styles": ["Crisp & Zesty"]}
    wine1 = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    cache1 = _fold_profile_dict(profile1, wine1, "down")
    assert _lists(cache1) == {
        "preferred_types": [], "preferred_grapes": ["Assyrtiko"], "preferred_styles": ["Crisp & Zesty"],
        "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    }
    reverted1 = _fold_profile_dict(cache1, wine1, "none", delta={})
    assert _lists(reverted1) == _lists(cache1)  # empty delta -> no-op

    # Case 2: partial overlap (style not preferred).
    profile2 = {**_EMPTY_PROFILE, "preferred_grapes": ["Assyrtiko"]}
    wine2 = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    cache2 = _fold_profile_dict(profile2, wine2, "down")
    assert _lists(cache2)["disliked_styles"] == ["Crisp & Zesty"]
    reverted2 = _fold_profile_dict(cache2, wine2, "none", delta={"added_disliked_styles": ["Crisp & Zesty"]})
    assert _lists(reverted2)["disliked_styles"] == []
    assert _lists(reverted2)["preferred_grapes"] == ["Assyrtiko"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
