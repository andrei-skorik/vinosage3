"""Unit tests for _classify_route and _is_recommend_followup (src/graph.py)."""
from __future__ import annotations


def _route(query: str, history=None) -> str:
    from src.graph import _classify_route
    return _classify_route(query, history)


def _followup(query: str, history) -> bool:
    from src.graph import _is_recommend_followup
    return _is_recommend_followup(query, history)


# ── Existing patterns (regression) ───────────────────────────────────────────

class TestExistingPatterns:
    def test_what_should_i_try(self):
        assert _route("What should I try today?") == "recommend"

    def test_whats_a_good_italian_red(self):
        assert _route("What's a good full-bodied Italian red?") == "recommend"

    def test_give_me_recommendations_for_tonight(self):
        # Imperative "give me ... recommendations" must route to recommend
        assert _route("Give me some recommendations for tonight") == "recommend"

    def test_show_me_recommendations(self):
        assert _route("Show me some wine recommendations please") == "recommend"

    def test_find_me_recommendations(self):
        assert _route("Can you find me a few recommendations?") == "recommend"

    def test_compare_before_educate(self):
        assert _route("Compare Malbec and Merlot styles") == "compare"

    def test_difference_between_routes_educate(self):
        assert _route("What's the difference between Malbec and Merlot?") == "educate"

    def test_what_is_tannin(self):
        assert _route("What is tannin?") == "educate"

    def test_food_query_stays_general(self):
        assert _route("What wine goes with steak?") == "general"

    def test_finnish_whats_a_good_routes_recommend(self):
        assert _route("Mikä on hyvä täyteläinen italialainen punaviini?") == "recommend"

    def test_finnish_mika_on_bare_stays_educate(self):
        assert _route("Mikä on tanniini?") == "educate"

    def test_german_was_ist_ein_gutes_routes_recommend(self):
        # "Was ist ein gutes X?" is recommend, not educate
        assert _route("Was ist ein gutes vollmundiges Rotwein aus Italien?") == "recommend"

    def test_german_was_ist_bare_stays_educate(self):
        # "Was ist Tannin?" is a genuine educational query
        assert _route("Was ist Tannin?") == "educate"

    def test_russian_chto_takoe_khoroshee_routes_recommend(self):
        # "Что такое хорошее X?" is recommend, not educate
        assert _route("Что такое хорошее итальянское красное вино?") == "recommend"

    def test_russian_chto_takoe_bare_stays_educate(self):
        # "Что такое танины?" is a genuine educational query
        assert _route("Что такое танины?") == "educate"


# ── Profile-explicit patterns ─────────────────────────────────────────────────

class TestProfileExplicitPatterns:
    def test_have_taste_profile_saved(self):
        assert _route("Yes, I have the taste profile saved") == "recommend"

    def test_have_a_profile(self):
        assert _route("I have a profile") == "recommend"

    def test_have_saved_profile(self):
        assert _route("I have a saved profile") == "recommend"

    def test_use_my_saved_preferences(self):
        assert _route("Use my saved preferences") == "recommend"

    def test_use_my_profile(self):
        assert _route("use my profile") == "recommend"

    def test_my_saved_preferences(self):
        assert _route("my saved preferences please") == "recommend"

    def test_show_profile_does_not_match(self):
        # "show my profile" has no "have/use/saved" guard → should NOT hit recommend
        result = _route("show my profile")
        assert result != "recommend"


# ── History-aware follow-up detection ────────────────────────────────────────

class TestIsRecommendFollowup:
    _BOT_ASKED_PROFILE = [
        {"role": "user",      "content": "What should I try today?"},
        {"role": "assistant", "content": (
            "To give you the best recommendation I need to know a bit more. "
            "If you have a taste profile saved, I can pull personalized picks. "
            "What's your mood — red or white?"
        )},
    ]
    _BOT_ASKED_MOOD = [
        {"role": "assistant", "content": (
            "Happy to help! What's your mood — something light and crisp, "
            "or rich and full-bodied? Any occasion in mind?"
        )},
    ]
    _BOT_EDUCATIONAL = [
        {"role": "assistant", "content": (
            "Tannins are polyphenolic compounds found in grape skins and seeds."
        )},
    ]

    def test_yes_i_have_profile_with_context(self):
        assert _followup("Yes, I have the taste profile saved", self._BOT_ASKED_PROFILE)

    def test_short_affirmative_after_mood_question(self):
        assert _followup("Red please, something bold", self._BOT_ASKED_MOOD)

    def test_short_price_reply(self):
        assert _followup("Around €15", self._BOT_ASKED_MOOD)

    def test_long_query_not_followup(self):
        # > 15 words → treated as independent request, not a follow-up
        long = (
            "Tell me about the history of wine production in France "
            "and its regional variations including Bordeaux and Burgundy in depth"
        )
        assert not _followup(long, self._BOT_ASKED_PROFILE)

    def test_no_history_not_followup(self):
        assert not _followup("Yes, I have a profile", None)

    def test_educational_context_not_followup(self):
        # Last bot message was educational — should NOT trigger recommend
        assert not _followup("interesting", self._BOT_EDUCATIONAL)

    def test_no_assistant_message_not_followup(self):
        history = [{"role": "user", "content": "Hello"}]
        assert not _followup("Yes", history)


# ── Full classify_route with history ─────────────────────────────────────────

class TestClassifyRouteWithHistory:
    def test_followup_routes_to_recommend(self):
        history = [
            {"role": "user",      "content": "What should I try today?"},
            {"role": "assistant", "content": (
                "If you have a taste profile saved, I can pull personalized "
                "recommendations. What's your mood?"
            )},
        ]
        assert _route("Yes, I have the taste profile saved", history) == "recommend"

    def test_short_color_reply_routes_to_recommend(self):
        history = [
            {"role": "assistant", "content": "What's your mood — red or white? Any preference?"},
        ]
        assert _route("Red please", history) == "recommend"

    def test_educational_followup_not_recommend(self):
        history = [
            {"role": "assistant", "content": "Tannins are polyphenolic compounds found in grape skins."},
        ]
        # Short reply but non-recommend context → general
        assert _route("interesting", history) == "general"
