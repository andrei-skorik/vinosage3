"""Unit tests for pair_with_food tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "src.tools.pair_with_food.get_active_wines_df"


class TestPairWithFood:
    def test_pair_steak_prefers_red(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "steak"})
        assert "pairings" in result
        types = {p["type"] for p in result["pairings"]}
        assert "Red" in types

    def test_pair_salmon_prefers_white(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "salmon"})
        assert "pairings" in result
        types = {p["type"] for p in result["pairings"]}
        assert "White" in types

    def test_pair_dessert_prefers_tawny(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "chocolate dessert"})
        assert "pairings" in result
        types = {p["type"] for p in result["pairings"]}
        assert "Tawny" in types

    def test_pair_bbq_prefers_red_rich(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            # "barbecue" is the recognised food noun (see _FOOD_NOUNS) —
            # the catalog wine's description says "ideal for barbecue ribs".
            result = pair_with_food.invoke({"dish": "barbecue ribs"})
        assert "pairings" in result
        types = {p["type"] for p in result["pairings"]}
        assert "Red" in types

    def test_pair_returns_rationale(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "pasta"})
        for p in result["pairings"]:
            assert "rationale" in p
            assert len(p["rationale"]) > 0

    def test_pair_max_price_respected(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "fish", "max_price_eur": 12.0})
        for p in result["pairings"]:
            if p["price_eur"] is not None:
                assert p["price_eur"] <= 12.0

    def test_pair_limit_respected(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "cheese", "limit": 2})
        assert len(result["pairings"]) <= 2

    def test_pair_prefer_type_filters_confirmed_matches(self, mock_df):
        """Both the Red (wine 1) and White (wine 2) mock wines mention 'fish'
        in their description — prefer_type should narrow confirmed pairings
        down to the requested type, not just suggest it as a preference."""
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            unfiltered = pair_with_food.invoke({"dish": "fish"})
            filtered = pair_with_food.invoke({"dish": "fish", "prefer_type": "Red"})
        assert {p["type"] for p in unfiltered["pairings"]} == {"Red", "White"}
        assert {p["type"] for p in filtered["pairings"]} == {"Red"}

    def test_pair_unknown_dish_returns_no_match(self, mock_df):
        """Anti-hallucination: a dish with zero catalog evidence must return
        no_match and an empty pairings list — never invented wines."""
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "xyzzy_unknown_food_123"})
        assert result.get("result") == "no_match"
        assert result["pairings"] == []

    def test_pair_empty_catalog_returns_error(self, empty_df):
        with patch(_MODULE, return_value=empty_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "steak"})
        assert "error" in result

    def test_pair_price_format(self, mock_df):
        with patch(_MODULE, return_value=mock_df):
            from src.tools.pair_with_food import pair_with_food
            result = pair_with_food.invoke({"dish": "pasta"})
        for p in result["pairings"]:
            if p["price_eur"] is not None:
                assert round(p["price_eur"], 2) == p["price_eur"]
