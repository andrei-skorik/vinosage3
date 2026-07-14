"""Parity test for the two fold-feedback implementations (Phase 3, steps 6f/6h).

`src.preferences.fold_feedback` (writes to Supabase) and
`src.ui.chat_view._fold_profile_dict` (the sidebar's in-memory mirror) are
DELIBERATELY duplicated call sites, but since step 6h they share the SAME
underlying pure math (`src.preferences._compute_and_apply_fold` /
`_revert_fold_delta`) rather than maintaining two independent copies — the
kind of divergence that caused the original Assyrtiko incident (step 6f).
This test runs both entry points on identical inputs and asserts the
resulting profiles agree, so a future edit to one that isn't mirrored in the
other still fails loudly here even though the math itself is now unified.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ui.chat_view import _fold_profile_dict

_EMPTY_PROFILE = {
    "expertise_level": "beginner",
    "preferred_types": [], "preferred_grapes": [], "preferred_countries": [],
    "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
    "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
    "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
}


def _run_fold_feedback(profile: dict, wine: dict, direction: str, delta: dict | None = None) -> dict:
    """Run fold_feedback against a mocked DB seeded with `profile` and
    capture the fields it would have upserted."""
    mock_resp = MagicMock()
    mock_resp.data = [dict(profile)]
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = mock_resp
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table

    with patch("src.preferences.get_service_db", return_value=mock_db), \
         patch("src.preferences.upsert_preferences") as mock_upsert:
        from src.preferences import fold_feedback
        fold_feedback("user-1", wine, direction, delta=delta)

    if not mock_upsert.called:
        return dict(profile)  # no-op fold: unchanged profile
    return {**profile, **mock_upsert.call_args.kwargs}


_LIST_FIELDS = (
    "preferred_types", "preferred_grapes", "preferred_styles",
    "disliked_types", "disliked_grapes", "disliked_styles",
)


def _sorted_lists(profile: dict) -> dict:
    return {f: sorted(profile.get(f) or []) for f in _LIST_FIELDS}


def _assert_parity(profile: dict, wine: dict, direction: str, delta: dict | None = None) -> None:
    via_db = _run_fold_feedback(profile, wine, direction, delta=delta)
    via_cache = _fold_profile_dict(profile, wine, direction, delta=delta)
    assert _sorted_lists(via_db) == _sorted_lists(via_cache), (
        f"fold_feedback vs _fold_profile_dict diverged for direction={direction!r}, "
        f"wine={wine!r}, starting profile={_sorted_lists(profile)!r}: "
        f"db={_sorted_lists(via_db)!r} cache={_sorted_lists(via_cache)!r}"
    )


def test_parity_down_vote_on_preferred_grape():
    """The exact Assyrtiko incident: both implementations must leave the
    preferred grape untouched and only fold the non-preferred style."""
    profile = {**_EMPTY_PROFILE, "preferred_grapes": ["Assyrtiko"]}
    wine = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    _assert_parity(profile, wine, "down")


def test_parity_down_vote_with_no_preferred_overlap():
    wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    _assert_parity(dict(_EMPTY_PROFILE), wine, "down")


def test_parity_up_vote_on_disliked_grape():
    profile = {**_EMPTY_PROFILE, "disliked_grapes": ["Assyrtiko"]}
    wine = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}
    _assert_parity(profile, wine, "up")


def test_parity_up_vote_from_empty_profile():
    wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    _assert_parity(dict(_EMPTY_PROFILE), wine, "up")


def test_parity_toggle_off_without_delta_is_a_no_op():
    """Phase 3 step 6h: toggle-off with no recorded delta (legacy row, or a
    fold that genuinely applied nothing) reverts NOTHING in both
    implementations — no more blanket 'remove from both buckets'."""
    profile = {
        **_EMPTY_PROFILE,
        "preferred_grapes": ["Malbec"], "disliked_styles": ["Rich & Juicy"],
    }
    wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    via_db = _run_fold_feedback(profile, wine, "none", delta=None)
    via_cache = _fold_profile_dict(profile, wine, "none", delta=None)
    assert _sorted_lists(via_db) == _sorted_lists(profile)
    assert _sorted_lists(via_cache) == _sorted_lists(profile)


def test_parity_toggle_off_with_delta_reverts_exactly_that():
    """With a recorded delta, both implementations revert exactly the
    added/removed values it names — the exact inverse of the fold, not a
    blanket wipe (Phase 3 step 6h)."""
    profile = {
        **_EMPTY_PROFILE,
        "preferred_grapes": ["Malbec"], "disliked_styles": ["Rich & Juicy"],
    }
    wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}
    delta = {"added_disliked_styles": ["Rich & Juicy"]}
    _assert_parity(profile, wine, "none", delta=delta)
    # And explicitly: the manually-set preferred grape survives, only the
    # fold's own addition is reverted.
    via_cache = _fold_profile_dict(profile, wine, "none", delta=delta)
    assert via_cache["preferred_grapes"] == ["Malbec"]
    assert via_cache["disliked_styles"] == []


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
