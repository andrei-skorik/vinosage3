"""Unit tests for calculate_budget tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "src.tools.calculate_budget.get_active_wines_df"


class TestCalculateBudget:
    def test_basic_basket_returns_correct_count(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 30.0, "quantity": 3})
        assert "basket" in result
        assert result["selected_count"] == 3

    def test_within_budget_flag(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 30.0, "quantity": 3})
        assert result["within_budget"] is True
        assert result["grand_total_eur"] <= 30.0

    def test_per_bottle_ceiling_calculated(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 30.0, "quantity": 3})
        assert result["per_bottle_ceiling_eur"] == 10.0  # 30 / 3

    def test_strategy_cheapest_picks_lowest_prices(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({
                "total_eur": 50.0, "quantity": 3, "strategy": "cheapest"
            })
        prices = sorted(b["price_eur"] for b in result["basket"])
        # cheapest strategy should pick the lowest available
        assert prices[0] == min(prices)

    def test_strategy_maximize_quality_picks_highest_within_ceiling(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({
                "total_eur": 50.0, "quantity": 3, "strategy": "maximize_quality"
            })
        assert result["selected_count"] == 3
        # prices should be sorted descending (highest first)
        prices = [b["price_eur"] for b in result["basket"]]
        assert prices == sorted(prices, reverse=True)

    def test_type_filter_applied(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({
                "total_eur": 50.0, "quantity": 2, "type": "White"
            })
        for b in result["basket"]:
            assert b["type"] == "White"

    def test_budget_too_small_returns_no_match(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 1.0, "quantity": 3})
        assert "error" in result
        assert result["error"]["code"] == "NO_MATCH"

    def test_repeat_wines_when_fewer_unique_than_quantity(self, mock_df):
        # only 1 White wine in catalog → must repeat to fill 3
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({
                "total_eur": 50.0, "quantity": 3, "type": "White"
            })
        assert result["selected_count"] == 3
        titles = [b["title"] for b in result["basket"]]
        assert titles.count("Weingut Test Riesling") == 3

    def test_grand_total_matches_sum_of_basket(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 40.0, "quantity": 3})
        expected = round(sum(b["price_eur"] for b in result["basket"]), 2)
        assert result["grand_total_eur"] == expected

    def test_empty_catalog_returns_error(self, empty_df):
        with patch(_MODULE, return_value=empty_df):
            from src.tools.calculate_budget import calculate_budget
            result = calculate_budget.invoke({"total_eur": 30.0, "quantity": 3})
        assert "error" in result
        assert result["error"]["code"] == "INTERNAL"
