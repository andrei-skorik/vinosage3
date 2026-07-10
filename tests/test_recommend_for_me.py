"""Unit tests for recommend_for_me — profile-conditioned recommendations.

The tool is built per-request via build_recommend_for_me_tool(profile)
(SPEC §3.3), so each test builds its own tool bound to the profile under test.
"""
from __future__ import annotations

from unittest.mock import patch

_MODULE = "src.tools.recommend_for_me.get_active_wines_df"


class TestRecommendForMe:
    def test_success_path_returns_only_catalog_wines(self, mock_df):
        catalog_ids = set(mock_df["wine_id"].tolist())
        profile = {
            "preferred_types": ["Red"],
            "preferred_styles": ["Rich & Juicy"],
        }
        with patch(_MODULE, return_value=mock_df):
            from src.tools.recommend_for_me import build_recommend_for_me_tool
            tool = build_recommend_for_me_tool(profile)
            result = tool.invoke({"occasion": None, "max_price_eur": None, "limit": 3})

        assert "recommendations" in result
        assert result["count"] >= 1
        for rec in result["recommendations"]:
            assert rec["wine_id"] in catalog_ids
            assert rec["type"] == "Red"

    def test_empty_profile_returns_diverse_general_picks(self, mock_df):
        """Empty profile → diverse picks from catalog, not an empty list asking questions."""
        with patch(_MODULE, return_value=mock_df):
            from src.tools.recommend_for_me import build_recommend_for_me_tool
            tool = build_recommend_for_me_tool({})
            result = tool.invoke({"occasion": None, "max_price_eur": None, "limit": 3})

        assert result["result"] == "no_profile_general"
        assert len(result["recommendations"]) > 0
        assert "agent_instruction" in result
        catalog_ids = set(mock_df["wine_id"].tolist())
        for rec in result["recommendations"]:
            assert rec["wine_id"] in catalog_ids

    def test_non_catalog_grape_returns_no_catalog_match(self, mock_df):
        """The profile's preferred grape doesn't exist anywhere in the
        catalog — the cardinal rule (SPEC §5.3) forbids inventing a wine to
        satisfy it; the tool must say so plainly instead."""
        profile = {"preferred_grapes": ["Assyrtiko"]}
        with patch(_MODULE, return_value=mock_df):
            from src.tools.recommend_for_me import build_recommend_for_me_tool
            tool = build_recommend_for_me_tool(profile)
            result = tool.invoke({"occasion": None, "max_price_eur": None, "limit": 3})

        assert result["result"] == "no_catalog_match"
        assert result["recommendations"] == []
        assert "agent_instruction" in result
        assert "Assyrtiko" in result["agent_instruction"]

    def test_disliked_style_excludes_matching_wines(self, mock_df):
        """Porto Test Tawny is the catalog's only 'Sweet & Rich' wine —
        disliking that style must exclude it even if type would otherwise match."""
        profile = {"preferred_types": ["Tawny"], "disliked_styles": ["Sweet & Rich"]}
        with patch(_MODULE, return_value=mock_df):
            from src.tools.recommend_for_me import build_recommend_for_me_tool
            tool = build_recommend_for_me_tool(profile)
            result = tool.invoke({"occasion": None, "max_price_eur": None, "limit": 3})

        assert result["result"] == "no_catalog_match"

    def test_max_price_eur_arg_overrides_profile(self, mock_df):
        profile = {"preferred_types": ["Red"], "max_price_eur_cents": 5000}
        with patch(_MODULE, return_value=mock_df):
            from src.tools.recommend_for_me import build_recommend_for_me_tool
            tool = build_recommend_for_me_tool(profile)
            result = tool.invoke({"occasion": None, "max_price_eur": 9.5, "limit": 3})

        for rec in result["recommendations"]:
            assert rec["price_eur"] <= 9.5
