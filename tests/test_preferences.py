"""Unit tests for src/preferences.py — explicit-signal extraction (SPEC §5.3)
and the feedback fold rule (SPEC §5.4)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

_CATALOG_MODULE = "src.preferences.get_active_wines_df"


class TestDetectPreferenceSignals:
    def test_explicit_positive_grape_in_catalog(self, mock_df):
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            signals = detect_preference_signals("I love Malbec", {})
        assert "Malbec" in signals["preferred_grapes"]

    def test_explicit_negative_style_signal(self, mock_df):
        """'Sweet & Rich' is the only catalog style containing 'sweet' —
        disliking sweet wines must fold into disliked_styles."""
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            signals = detect_preference_signals("I can't stand sweet wines", {})
        assert "Sweet & Rich" in signals["disliked_styles"]

    def test_sentence_boundary_keeps_trailing_question_out_of_clause(self, mock_df):
        """A clause must stop at the first sentence terminator — a wine named
        in an unrelated trailing question must never be folded into the
        preceding dislike clause (regression: this used to wrongly tag
        Riesling as disliked)."""
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            signals = detect_preference_signals("I hate Chardonnay. What about Riesling?", {})
        assert "Riesling" not in signals.get("disliked_grapes", [])
        assert "Riesling" not in signals.get("preferred_grapes", [])

    def test_non_catalog_term_lands_in_notes_not_dropped(self, mock_df):
        """A term with no catalog match must still be recorded somewhere
        (notes) — the cardinal rule forbids inventing a structured-array
        match, but it must not be silently lost either."""
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            signals = detect_preference_signals("I love Glerb", {})
        assert all("Glerb" not in (signals.get(f) or []) for f in (
            "preferred_types", "preferred_grapes", "preferred_countries",
            "preferred_styles", "preferred_characteristics",
        ))
        assert signals.get("notes")
        assert "Glerb" in signals["notes"]

    def test_casual_mention_triggers_no_signal(self, mock_df):
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            signals = detect_preference_signals("I had a Malbec last night, it was nice.", {})
        assert signals == {}

    def test_idempotent_repeat_statement_returns_empty_delta(self, mock_df):
        from src.preferences import detect_preference_signals
        with patch(_CATALOG_MODULE, return_value=mock_df):
            first = detect_preference_signals("I love Malbec", {})
            second = detect_preference_signals("I love Malbec", first)
        assert second == {}


def _mock_db_returning(profile: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.data = [profile]
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = mock_resp
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table
    return mock_db


class TestFoldFeedback:
    def test_down_vote_on_preferred_grape_leaves_it_preferred_not_disliked(self):
        """SPEC §5.4: an explicit positive preference wins over a single 👎.
        Regression for the Assyrtiko incident (Phase 3 step 6f) — a 👎 must
        NEVER move a value out of preferred_* into disliked_*. The wine's
        style, which was NOT preferred, is legitimately folded into
        disliked_styles — same incident, correct half of the behavior."""
        existing_profile = {
            "expertise_level": "beginner",
            "preferred_types": [], "preferred_grapes": ["Assyrtiko"], "preferred_countries": [],
            "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
            "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
            "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
        }
        mock_db = _mock_db_returning(existing_profile)
        wine = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}

        with patch("src.preferences.get_service_db", return_value=mock_db), \
             patch("src.preferences.upsert_preferences") as mock_upsert:
            from src.preferences import fold_feedback
            fold_feedback("user-1", wine, "down")

        mock_upsert.assert_called_once()
        kwargs = mock_upsert.call_args.kwargs
        # Assyrtiko stays preferred — never removed by a 👎.
        assert "Assyrtiko" in kwargs["preferred_grapes"]
        assert "Assyrtiko" not in kwargs["disliked_grapes"]
        # Style was not preferred, so it legitimately lands in disliked.
        assert "Crisp & Zesty" in kwargs["disliked_styles"]
        # Type is excluded from disliked per SPEC §5.4
        assert "White" not in kwargs["disliked_types"]

    def test_down_vote_with_no_preferred_overlap_folds_into_disliked(self):
        """No standing preference on grape/style -> both fold into
        disliked_* as before (the non-conflicting, ordinary case)."""
        empty_profile = {
            "expertise_level": "beginner",
            "preferred_types": [], "preferred_grapes": [], "preferred_countries": [],
            "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
            "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
            "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
        }
        mock_db = _mock_db_returning(empty_profile)
        wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}

        with patch("src.preferences.get_service_db", return_value=mock_db), \
             patch("src.preferences.upsert_preferences") as mock_upsert:
            from src.preferences import fold_feedback
            fold_feedback("user-1", wine, "down")

        kwargs = mock_upsert.call_args.kwargs
        assert "Malbec" in kwargs["disliked_grapes"]
        assert "Rich & Juicy" in kwargs["disliked_styles"]
        assert "Red" not in kwargs["disliked_types"]

    def test_up_vote_on_disliked_grape_moves_it_into_preferred(self):
        """A fresh explicit 👍 beats a stored dislike: the grape is removed
        from disliked_grapes and added to preferred_grapes."""
        existing_profile = {
            "expertise_level": "beginner",
            "preferred_types": [], "preferred_grapes": [], "preferred_countries": [],
            "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
            "disliked_types": [], "disliked_grapes": ["Assyrtiko"], "disliked_styles": [],
            "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
        }
        mock_db = _mock_db_returning(existing_profile)
        wine = {"type": "White", "grape": "Assyrtiko", "style": "Crisp & Zesty"}

        with patch("src.preferences.get_service_db", return_value=mock_db), \
             patch("src.preferences.upsert_preferences") as mock_upsert:
            from src.preferences import fold_feedback
            fold_feedback("user-1", wine, "up")

        kwargs = mock_upsert.call_args.kwargs
        assert "Assyrtiko" in kwargs["preferred_grapes"]
        assert "Assyrtiko" not in kwargs["disliked_grapes"]

    def test_up_vote_adds_type_grape_style_to_preferred(self):
        empty_profile = {
            "expertise_level": "beginner",
            "preferred_types": [], "preferred_grapes": [], "preferred_countries": [],
            "preferred_regions": [], "preferred_styles": [], "preferred_characteristics": [],
            "disliked_types": [], "disliked_grapes": [], "disliked_styles": [],
            "min_price_eur_cents": None, "max_price_eur_cents": None, "notes": None,
        }
        mock_resp = MagicMock()
        mock_resp.data = [empty_profile]
        mock_table = MagicMock()
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = mock_resp
        mock_db = MagicMock()
        mock_db.table.return_value = mock_table

        wine = {"type": "Red", "grape": "Malbec", "style": "Rich & Juicy"}

        with patch("src.preferences.get_service_db", return_value=mock_db), \
             patch("src.preferences.upsert_preferences") as mock_upsert:
            from src.preferences import fold_feedback
            fold_feedback("user-1", wine, "up")

        kwargs = mock_upsert.call_args.kwargs
        assert "Red" in kwargs["preferred_types"]
        assert "Malbec" in kwargs["preferred_grapes"]
        assert "Rich & Juicy" in kwargs["preferred_styles"]
