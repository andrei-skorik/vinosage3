"""Unit tests for src/logging_db.py's direct DB-facing functions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.logging_db import delete_all_feedback, erase_user_history, get_feedback_ratings


def test_delete_all_feedback_deletes_by_user_id_only():
    """GDPR 'Forget everything about me' (US-004): every recommendation_feedback
    row for this user must be removed, with no wine_id filter — unlike the
    per-wine delete_feedback used by the toggle-off UI flow."""
    mock_table = MagicMock()
    mock_table.delete.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table

    with patch("src.logging_db._db", return_value=mock_db):
        delete_all_feedback("user-1")

    mock_db.table.assert_called_once_with("recommendation_feedback")
    mock_table.delete.assert_called_once()
    mock_table.eq.assert_called_once_with("user_id", "user-1")
    mock_table.execute.assert_called_once()


def test_delete_all_feedback_swallows_exceptions():
    """A delete failure must never raise past this function's boundary —
    same best-effort principle as delete_preferences/delete_feedback."""
    mock_db = MagicMock()
    mock_db.table.side_effect = RuntimeError("db down")

    with patch("src.logging_db._db", return_value=mock_db):
        delete_all_feedback("user-1")  # must not raise


def test_erase_user_history_anonymizes_query_logs_and_nulls_security_events():
    """GDPR 'Forget everything about me' (US-004, Phase 4 step 4c): identity
    unlinked + content scrubbed, NEVER hard-deleted (a hard delete would
    cascade into token_usage and shrink the daily cost cap's running total).
    security_events.user_id is also nulled for the same user — its own FK's
    ON DELETE SET NULL only fires if the auth user row itself is deleted,
    which forget-me does not do."""
    tables: dict[str, MagicMock] = {}

    def _make_table(name):
        m = MagicMock()
        m.update.return_value = m
        m.eq.return_value = m
        tables[name] = m
        return m

    mock_db = MagicMock()
    mock_db.table.side_effect = _make_table

    with patch("src.logging_db._db", return_value=mock_db):
        result = erase_user_history("user-1")

    assert result is True

    ql = tables["query_logs"]
    ql.update.assert_called_once_with({
        "user_id": None, "user_query": "[erased]", "final_answer": "[erased]",
    })
    ql.eq.assert_called_once_with("user_id", "user-1")
    ql.execute.assert_called_once()

    sec = tables["security_events"]
    sec.update.assert_called_once_with({"user_id": None})
    sec.eq.assert_called_once_with("user_id", "user-1")
    sec.execute.assert_called_once()


def test_erase_user_history_swallows_exceptions_and_returns_false():
    """A DB failure must never raise past this function's boundary — same
    best-effort principle as delete_all_feedback — but MUST surface False so
    the forget-me UI shows its generic error instead of a false success."""
    mock_db = MagicMock()
    mock_db.table.side_effect = RuntimeError("db down")

    with patch("src.logging_db._db", return_value=mock_db):
        result = erase_user_history("user-1")  # must not raise

    assert result is False


def test_get_feedback_ratings_returns_composite_keyed_map():
    """Phase 3.1 fix_feedback_hydration: rehydrating chat history needs to
    recover exactly which (query_id, wine_id) pairs this user rated — not
    just the latest rating per wine (get_latest_ratings' wine_id-only shape,
    itself part of the cross-turn highlight leak — see PHASE3_HANDOFF.md
    Backlog #17 — and now replaced by this function)."""
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.in_.return_value = mock_table
    mock_table.execute.return_value.data = [
        {"query_id": "q1", "wine_id": "w-1", "rating": "up"},
        {"query_id": "q2", "wine_id": "w-1", "rating": "down"},
    ]
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table

    with patch("src.logging_db._db", return_value=mock_db):
        result = get_feedback_ratings("user-1", ["q1", "q2"])

    assert result == {("q1", "w-1"): "up", ("q2", "w-1"): "down"}
    mock_db.table.assert_called_once_with("recommendation_feedback")
    mock_table.eq.assert_called_once_with("user_id", "user-1")
    mock_table.in_.assert_called_once_with("query_id", ["q1", "q2"])


def test_get_feedback_ratings_batches_large_query_id_lists():
    from src import logging_db

    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.in_.return_value = mock_table
    mock_table.execute.return_value.data = []
    mock_db = MagicMock()
    mock_db.table.return_value = mock_table

    many_ids = [f"q{i}" for i in range(250)]  # > _BATCH_SIZE (200)
    with patch("src.logging_db._db", return_value=mock_db):
        get_feedback_ratings("user-1", many_ids)

    assert mock_table.in_.call_count == 2
    first_batch = mock_table.in_.call_args_list[0].args[1]
    second_batch = mock_table.in_.call_args_list[1].args[1]
    assert len(first_batch) == logging_db._BATCH_SIZE
    assert len(second_batch) == 50


def test_get_feedback_ratings_returns_empty_for_no_query_ids():
    with patch("src.logging_db._db") as mock_db_fn:
        result = get_feedback_ratings("user-1", [])

    assert result == {}
    mock_db_fn.assert_not_called()  # empty input is a fast path, no DB round-trip


def test_get_feedback_ratings_swallows_exceptions():
    """A read failure must never raise past this function's boundary — a
    missing highlight is cosmetic, never worth breaking the render over."""
    mock_db = MagicMock()
    mock_db.table.side_effect = RuntimeError("db down")

    with patch("src.logging_db._db", return_value=mock_db):
        result = get_feedback_ratings("user-1", ["q1"])  # must not raise

    assert result == {}


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
