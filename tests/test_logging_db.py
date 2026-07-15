"""Unit tests for src/logging_db.py's direct DB-facing functions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.logging_db import delete_all_feedback


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


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
