"""Multilingual routing coverage for the 30 food nouns (Phase 4, step 2).

The 30 nouns added to the evidence sets in Phase 3 step 3 (prawn, crab,
soup, stew, burger, ...) were English-only in the ROUTING set
(agent._FOOD_QUERY_KWS / agent._RU_FOOD_STEMS) — a German/Finnish/Russian
user asking about them was never classified as a food query, so the
mandatory pair_with_food path was never forced and the layer-2/3 evidence
filters never engaged for those turns.

This file tests ROUTING DETECTION ONLY (agent._is_food_query). The three
evidence sets (pair_with_food._FOOD_NOUNS, agent._FOOD_KWS,
app._HIST_FOOD_KWS) match against ENGLISH catalog descriptions and must
NOT gain non-English words — tests/test_food_kws_sync.py is the guard for
that invariant; this file additionally asserts it directly (belt-and-braces).
"""
from __future__ import annotations

from src.agent import _is_food_query


# ── German ────────────────────────────────────────────────────────────────────


def test_de_pudding():
    assert _is_food_query("Welcher Wein passt zu Pudding?", None) is True


def test_de_suppen_plural_inflected():
    """Inflected/plural form: Suppen (plural of Suppe)."""
    assert _is_food_query("Welcher Wein passt zu Suppen?", None) is True


def test_de_oktopus():
    assert _is_food_query("Ich hätte gerne einen Wein zu Oktopus", None) is True


def test_de_wachteln():
    assert _is_food_query("Welcher Wein passt zu Wachteln?", None) is True


def test_de_negative_control_no_food_words():
    assert _is_food_query("Welchen Rotwein empfehlen Sie?", None) is False
    assert _is_food_query("Was ist ein guter Rotwein unter 20 Euro?", None) is False


# ── Finnish ───────────────────────────────────────────────────────────────────


def test_fi_keittoon_soup_inflected():
    """Inflected form: keittoon (illative of keitto, 'soup')."""
    assert _is_food_query("Mikä viini sopii keittoon?", None) is True


def test_fi_katkaravun_prawn_inflected():
    """Inflected form: katkaravun (genitive of katkarapu, 'prawn')."""
    assert _is_food_query("Suosittele viiniä katkaravun kanssa", None) is True


def test_fi_burgeriin():
    assert _is_food_query("Mikä viini sopii burgeriin?", None) is True


def test_fi_mustekala():
    assert _is_food_query("Entä mustekala, mikä viini sopii?", None) is True


def test_fi_negative_control_no_food_words():
    assert _is_food_query("Suosittele hyvä punaviini", None) is False
    assert _is_food_query("Mikä on paras viini illalliselle?", None) is False


# ── Russian ───────────────────────────────────────────────────────────────────


def test_ru_pelmenyam_dumplings_inflected():
    """Inflected form: пельменям (dative plural of пельмень, 'dumplings')."""
    assert _is_food_query("Какое вино подойдет к пельменям?", None) is True


def test_ru_brauni():
    assert _is_food_query("Посоветуй вино к брауни", None) is True


def test_ru_perepelu_quail_inflected():
    assert _is_food_query("Что подходит к перепелу?", None) is True


def test_ru_fazanu_pheasant_inflected():
    assert _is_food_query("Вино к фазану", None) is True


def test_ru_negative_control_no_food_words():
    assert _is_food_query("Порекомендуй красное вино", None) is False
    assert _is_food_query("Какое вино самое дорогое в каталоге?", None) is False


# ── Evidence sets untouched (belt-and-braces alongside test_food_kws_sync.py) ─


def test_english_evidence_sets_still_equal_and_untouched():
    """This step touches ROUTING detection only (_FOOD_QUERY_KWS /
    _RU_FOOD_STEMS / the new _FI_FOOD_STEMS) — the three ENGLISH evidence
    sets must remain exactly equal to each other, as
    tests/test_food_kws_sync.py already verifies in full detail. Re-asserted
    here directly so this file stands on its own as evidence nothing
    non-English leaked into them."""
    from src import agent
    import app
    from src.tools.pair_with_food import _FOOD_NOUNS

    l1, l2, l3 = set(_FOOD_NOUNS), set(agent._FOOD_KWS), set(app._HIST_FOOD_KWS)
    assert l1 == l2 == l3
    # None of the new non-English words leaked into the evidence sets.
    non_english_markers = {"suppen", "пельменям", "keittoon", "wachteln", "фазану"}
    assert not (non_english_markers & l1)


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
