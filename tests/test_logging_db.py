"""Unit tests for src/logging_db.py's direct DB-facing functions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.logging_db import delete_all_feedback, erase_user_history


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


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
