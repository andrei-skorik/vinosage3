"""Unit tests for wine_stats tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "src.tools.wine_stats.get_active_wines_df"


class TestWineStats:
    def test_count_all_wines(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "count"})
        assert "value" in result
        assert result["value"] == 6

    def test_count_filtered_by_type(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({
                "metric": "count",
                "filters": {"type": "Red"},
            })
        assert result["value"] == 3

    def test_avg_price_returns_float(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "avg_price"})
        assert "value_eur" in result
        expected = round((1500 + 1200 + 900 + 1100 + 2500 + 1800) / 6 / 100, 2)
        assert abs(result["value_eur"] - expected) < 0.01

    def test_min_price(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "min_price"})
        assert result["value_eur"] == 9.0  # Malbec €9.00

    def test_max_price(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "max_price"})
        assert result["value_eur"] == 25.0  # Tawny €25.00

    def test_avg_abv_is_correct(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "avg_abv"})
        assert "value_abv" in result
        expected = round((13.5 + 11.5 + 14.0 + 12.5 + 19.5 + 12.5) / 6, 2)
        assert abs(result["value_abv"] - expected) < 0.01

    def test_invalid_metric_returns_error(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "median_price"})
        assert "error" in result
        assert result["error"]["code"] == "INVALID_ARGS"

    def test_filter_no_match_returns_no_match_error(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({
                "metric": "count",
                "filters": {"country": "Japan"},
            })
        assert "error" in result
        assert result["error"]["code"] == "NO_MATCH"

    def test_price_value_is_native_float_not_numpy(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "avg_price"})
        # Must be JSON-serialisable (native float, not np.float64)
        import json
        json.dumps(result)  # would raise TypeError if numpy type

    def test_sample_size_reported(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "min_price"})
        assert "sample_size" in result
        assert isinstance(result["sample_size"], int)

    def test_filter_by_max_price_eur(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({
                "metric": "count",
                "filters": {"max_price_eur": 12.0},
            })
        # Riesling €12, Malbec €9, Rosé €11 → 3
        assert result["value"] == 3

    def test_empty_catalog_returns_error(self, empty_df):
        with patch(_MODULE, return_value=empty_df):
            from src.tools.wine_stats import wine_stats
            result = wine_stats.invoke({"metric": "count"})
        assert "error" in result
        assert result["error"]["code"] == "INTERNAL"
