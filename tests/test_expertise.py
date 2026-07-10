"""Unit tests for expertise-level personalisation of the system prompt."""
from __future__ import annotations

from unittest.mock import patch


def _system_msg(expertise_level: str) -> str:
    from src.agent import _build_messages
    msgs = _build_messages(
        query="What should I try?",
        locale="en",
        history=None,
        rag_context=[],
        expertise_level=expertise_level,
    )
    return next(m["content"] for m in msgs if m["role"] == "system")


class TestExpertiseNotes:
    def test_beginner_note_present(self):
        msg = _system_msg("beginner")
        assert "beginner" in msg.lower()
        assert "plain" in msg.lower()

    def test_enthusiast_note_present(self):
        msg = _system_msg("enthusiast")
        assert "enthusiast" in msg.lower()

    def test_connoisseur_note_present(self):
        msg = _system_msg("connoisseur")
        assert "connoisseur" in msg.lower()
        assert "peer" in msg.lower()

    def test_unknown_level_falls_back_to_beginner(self):
        beginner_msg = _system_msg("beginner")
        unknown_msg  = _system_msg("sommelier_god")
        assert beginner_msg == unknown_msg

    def test_notes_are_distinct(self):
        b = _system_msg("beginner")
        e = _system_msg("enthusiast")
        c = _system_msg("connoisseur")
        assert b != e
        assert e != c
        assert b != c

    def test_default_is_beginner(self):
        from src.agent import _build_messages
        default_msgs = _build_messages("What should I try?", "en", None, [])
        default_sys  = next(m["content"] for m in default_msgs if m["role"] == "system")
        assert default_sys == _system_msg("beginner")
