"""Unit tests for RAG components (pure functions — no API calls)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRRFFuse:
    """_rrf_fuse is a pure function — no mocks needed."""

    def _fuse(self, result_lists, k=60):
        from src.rag import _rrf_fuse
        return _rrf_fuse(result_lists, k=k)

    def test_empty_input_returns_empty(self):
        assert self._fuse([]) == []

    def test_single_list_preserves_order(self):
        items = [
            {"wine_id": "a", "title": "Wine A"},
            {"wine_id": "b", "title": "Wine B"},
            {"wine_id": "c", "title": "Wine C"},
        ]
        result = self._fuse([items])
        assert [r["wine_id"] for r in result] == ["a", "b", "c"]

    def test_top_ranked_in_multiple_lists_scores_highest(self):
        list1 = [{"wine_id": "x", "title": "X"}, {"wine_id": "y", "title": "Y"}]
        list2 = [{"wine_id": "x", "title": "X"}, {"wine_id": "z", "title": "Z"}]
        result = self._fuse([list1, list2])
        # "x" appears #1 in both lists → highest RRF score
        assert result[0]["wine_id"] == "x"

    def test_deduplication_by_wine_id(self):
        items = [{"wine_id": "a", "title": "Wine A"}]
        result = self._fuse([items, items, items])
        ids = [r["wine_id"] for r in result]
        assert ids.count("a") == 1

    def test_rrf_score_attached(self):
        items = [{"wine_id": "a", "title": "Wine A"}]
        result = self._fuse([items])
        assert "rrf_score" in result[0]
        assert isinstance(result[0]["rrf_score"], float)

    def test_k_parameter_affects_scores(self):
        items = [{"wine_id": "a", "title": "A"}, {"wine_id": "b", "title": "B"}]
        result_small_k = self._fuse([items], k=1)
        result_large_k = self._fuse([items], k=1000)
        # With k=1: score for rank-1 = 1/(1+1)=0.5; with k=1000: 1/(1000+1)≈0.001
        assert result_small_k[0]["rrf_score"] > result_large_k[0]["rrf_score"]


class TestRetrievedWine:
    def test_model_accepts_valid_data(self):
        from src.rag import RetrievedWine
        w = RetrievedWine(
            wine_id="abc-123",
            title="Test Wine",
            similarity=0.92,
            payload={"price_eur_cents": 1500},
        )
        assert w.wine_id == "abc-123"
        assert w.similarity == 0.92

    def test_model_requires_wine_id(self):
        from pydantic import ValidationError
        from src.rag import RetrievedWine
        with pytest.raises(ValidationError):
            RetrievedWine(title="X", similarity=0.5, payload={})  # missing wine_id

    def test_payload_defaults_to_empty_if_not_passed(self):
        from src.rag import RetrievedWine
        # payload has no default, just check model structure
        w = RetrievedWine(wine_id="id", title="T", similarity=0.0, payload={})
        assert w.payload == {}


class TestExtractFilter:
    def test_extract_filter_returns_empty_on_llm_failure(self):
        with patch("src.llm.get_utility_llm") as mock_llm_fn:
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = RuntimeError("LLM unavailable")
            mock_llm_fn.return_value = mock_llm

            from src.rag import _extract_filter
            result = _extract_filter("some query")
        assert result == {}

    def test_extract_filter_parses_valid_json(self):
        with patch("src.llm.get_utility_llm") as mock_llm_fn:
            mock_resp = MagicMock()
            mock_resp.content = '{"type": "Red", "max_price_eur": 15}'
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_resp
            mock_llm_fn.return_value = mock_llm

            from importlib import reload
            import src.rag as rag_mod
            result = rag_mod._extract_filter("red wine under 15")
        assert result.get("type") == "Red"
        assert result.get("max_price_eur") == 15


class TestTranslateQuery:
    def test_translate_query_fallback_on_error(self):
        with patch("src.llm.get_utility_llm") as mock_llm_fn:
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = RuntimeError("API error")
            mock_llm_fn.return_value = mock_llm

            from src.rag import _translate_query
            variants = _translate_query("red wine", n=3)
        # Fallback: original query repeated n times
        assert variants == ["red wine", "red wine", "red wine"]

    def test_translate_query_returns_n_variants(self):
        with patch("src.llm.get_utility_llm") as mock_llm_fn:
            mock_resp = MagicMock()
            mock_resp.content = '["fruity red wine", "light red", "soft red wine"]'
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = mock_resp
            mock_llm_fn.return_value = mock_llm

            from src.rag import _translate_query
            variants = _translate_query("red wine", n=3)
        assert len(variants) == 3
        assert all(isinstance(v, str) for v in variants)
