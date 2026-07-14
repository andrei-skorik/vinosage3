"""Tests for the 6g title-matching fix (the 'White Ash' incident)."""
from src.ui.chat_view import _title_in_response


CATALOG = "Leonidas Nassiakos ‘White Ash’ Assyrtiko 2020, Santorini"  # curly, as in DB


def test_the_white_ash_incident_curly_vs_straight():
    llm_text = "Leonidas Nassiakos 'White Ash' Assyrtiko 2020, Santorini — €30.67. Ripe and rounded."
    assert _title_in_response(CATALOG, llm_text) is True


def test_reverse_direction_straight_title_curly_text():
    assert _title_in_response(
        "Leonidas Nassiakos 'White Ash' Assyrtiko 2020, Santorini",
        "Try the Leonidas Nassiakos ‘White Ash’ Assyrtiko tonight.",
    ) is True


def test_plain_titles_still_match():
    assert _title_in_response(
        "Domaine Skouras Assyrtiko 2021/22, Nemea",
        "Domaine Skouras Assyrtiko — crisp and zesty.",
    ) is True


def test_absent_wine_still_rejected():
    assert _title_in_response(CATALOG, "Lyrarakis Assyrtiko is great tonight.") is False


def test_dash_and_nbsp_normalization():
    assert _title_in_response(
        "Viñalba ‘Cuvée Diane’ 2019/20, Mendoza",
        "Viñalba 'Cuvée Diane' is a bold pick.",
    ) is True


def test_vintage_and_region_stripping_unchanged():
    assert _title_in_response(
        "Whale Cove Sauvignon Blanc 2021/22, South Africa",
        "I suggest the Whale Cove Sauvignon Blanc.",
    ) is True


def test_empty_title_permissive_unchanged():
    assert _title_in_response("", "anything") is True
