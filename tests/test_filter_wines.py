"""Unit tests for filter_wines tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "src.tools.filter_wines.get_active_wines_df"


class TestFilterWines:
    def test_filter_by_type_red(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"type": "Red"})
        assert "wines" in result
        assert result["count"] == 3
        assert all(w["type"] == "Red" for w in result["wines"])

    def test_filter_by_type_white(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"type": "White"})
        assert result["count"] == 1
        assert result["wines"][0]["title"] == "Weingut Test Riesling"

    def test_filter_by_country_case_insensitive(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"country": "france"})
        assert result["count"] == 1
        assert result["wines"][0]["country"] == "France"

    def test_filter_by_grape_partial_match(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"grape": "Pinot"})
        assert result["count"] == 1
        assert "Pinot" in result["wines"][0]["grape"]

    def test_filter_max_price(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"max_price_eur": 12.0})
        # wines ≤ €12: Riesling (€12), Malbec (€9), Rosé (€11) → 3 wines
        assert result["count"] == 3
        for w in result["wines"]:
            assert w["price_eur"] <= 12.0

    def test_filter_min_price(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"min_price_eur": 15.0})
        # wines ≥ €15: Rouge (€15), Pinot (€18), Tawny (€25) → 3 wines
        assert result["count"] == 3
        for w in result["wines"]:
            assert w["price_eur"] >= 15.0

    def test_filter_price_range(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"min_price_eur": 10.0, "max_price_eur": 15.0})
        for w in result["wines"]:
            assert 10.0 <= w["price_eur"] <= 15.0

    def test_filter_min_abv(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"min_abv": 14.0})
        # Malbec (14.0), Tawny (19.5) → 2 wines
        assert result["count"] == 2
        for w in result["wines"]:
            assert w["abv_percent"] >= 14.0

    def test_filter_limit(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"limit": 2})
        assert len(result["wines"]) == 2

    def test_filter_invalid_type_returns_error(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"type": "Purple"})
        assert "error" in result
        assert result["error"]["code"] == "UNKNOWN_VALUE"

    def test_filter_no_match_returns_no_match_error(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"max_price_eur": 0.50})
        assert "error" in result
        assert result["error"]["code"] == "NO_MATCH"

    def test_filter_empty_catalog_returns_internal_error(self, empty_df):
        with patch(_MODULE, return_value=empty_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({})
        assert "error" in result
        assert result["error"]["code"] == "INTERNAL"

    def test_price_display_is_rounded_two_decimals(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"type": "Red"})
        for w in result["wines"]:
            if w["price_eur"] is not None:
                assert round(w["price_eur"], 2) == w["price_eur"]

    def test_nv_wine_displays_vintage_nv(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"type": "Tawny"})
        assert result["wines"][0]["vintage"] == "NV"

    def test_filter_region_partial_match(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.filter_wines import filter_wines
            result = filter_wines.invoke({"region": "Mendoz"})
        assert result["count"] == 1
        assert result["wines"][0]["title"] == "Bodega Test Malbec"
