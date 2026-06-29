"""Unit tests for compare_wines tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "src.tools.compare_wines.get_active_wines_df"


class TestCompareWines:
    def test_compare_two_exact_titles(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Chateau Test Rouge", "Weingut Test Riesling"]
            })
        assert "comparison" in result
        assert len(result["comparison"]) == 2

    def test_compare_three_wines(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": [
                    "Chateau Test Rouge",
                    "Bodega Test Malbec",
                    "Cantina Test Pinot",
                ]
            })
        assert "comparison" in result
        assert len(result["comparison"]) == 3

    def test_fuzzy_match_resolves_typo(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            # One character off from "Chateau Test Rouge"
            result = compare_wines.invoke({
                "wines": ["Chateau Test Roug", "Bodega Test Malbec"]
            })
        assert "comparison" in result
        matched = {w["title"] for w in result["comparison"]}
        assert "Chateau Test Rouge" in matched

    def test_unknown_wine_returns_wine_not_found(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Completely Unknown XYZ 2099", "Bodega Test Malbec"]
            })
        assert "error" in result
        assert result["error"]["code"] == "WINE_NOT_FOUND"

    def test_not_found_includes_alternatives(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Completely Unknown Wine ZZZZ", "Weingut Test Riesling"]
            })
        assert "error" in result
        assert "alternatives" in result["error"]["message"] or "not found" in result["error"]["message"].lower()

    def test_comparison_includes_price(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Chateau Test Rouge", "Bodega Test Malbec"]
            })
        assert "comparison" in result
        for w in result["comparison"]:
            assert "price_eur" in w
            assert w["price_eur"] is not None

    def test_comparison_includes_abv_country_grape(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Chateau Test Rouge", "Weingut Test Riesling"]
            })
        for w in result["comparison"]:
            assert "abv_percent" in w
            assert "country" in w
            assert "grape" in w

    def test_empty_catalog_returns_error(self, empty_df):
        with patch(_MODULE, return_value=empty_df):
            from src.tools.compare_wines import compare_wines
            result = compare_wines.invoke({
                "wines": ["Chateau Test Rouge", "Any Wine"]
            })
        assert "error" in result
        assert result["error"]["code"] == "INTERNAL"
