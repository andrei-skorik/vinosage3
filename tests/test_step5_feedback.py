"""Tests for Phase 3, step 5 — feedback features №1 / №2 / №4.

№1: recommend_for_me never re-recommends a wine the user has an active 👎 on.
№2/№4: pure aggregation math for the admin "Recommendation feedback" section.

Catalog and preferences I/O are monkeypatched — no DB, no LLM.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import src.preferences as prefs
import src.tools.recommend_for_me as rfm
from src.feedback_insights import feedback_aggregates


# ── Shared mock catalog ───────────────────────────────────────────────────────


def _mock_df() -> pd.DataFrame:
    cols = dict(
        wine_id=["w1", "w2", "w3", "w4"],
        title=["Guvnor", "Bold Malbec", "Crisp White", "Pink Fizz"],
        type=["Red", "Red", "White", "Sparkling"],
        grape=["Tempranillo", "Malbec", "Albariño", "Glera"],
        country=["Spain", "Argentina", "Spain", "Italy"],
        region=["Rioja", "Mendoza", "Rías Baixas", "Veneto"],
        style=["Rich & Juicy", "Rich & Juicy", "Crisp & Zesty", "Light & Bubbly"],
        characteristics=["plum, vanilla", "blackberry", "citrus", "apple"],
        price_eur_cents=[1179, 1499, 1299, 999],
        is_active=[True, True, True, True],
        description=["d1", "d2", "d3", "d4"],
    )
    return pd.DataFrame(cols)


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    monkeypatch.setattr(rfm, "get_active_wines_df", _mock_df)


_RED_PROFILE = {"preferred_types": ["Red"]}


def _titles(result: dict[str, Any]) -> list[str]:
    return [r["title"] for r in result.get("recommendations", [])]


# ── №1: exclusion of down-rated wines ─────────────────────────────────────────


def test_downrated_wine_never_rerecommended(monkeypatch):
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w2"})
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id="u1")
    assert "Guvnor" in _titles(res)
    assert "Bold Malbec" not in _titles(res)  # w2 is down-rated → excluded


def test_downrated_excluded_from_diverse_picks_too(monkeypatch):
    """Empty profile + feedback: the no_profile_general path must also
    respect the exclusion — a cleared profile doesn't reset rejections."""
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w1", "w2"})
    res = rfm._build({}, None, None, 5, user_id="u1")
    assert res["result"] == "no_profile_general"
    got = _titles(res)
    assert "Guvnor" not in got and "Bold Malbec" not in got
    assert got  # something is still recommended


def test_all_matches_downrated_gets_honest_result(monkeypatch):
    """When the ONLY thing emptying the result is the user's own 👎 history,
    the tool must say that (all_downrated) — not the misleading
    no_catalog_match — and must name no wines."""
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w1", "w2"})
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id="u1")
    assert res["result"] == "all_downrated"
    assert res["recommendations"] == []
    assert "thumbs-down" in res["agent_instruction"]
    for title in ("Guvnor", "Bold Malbec"):
        assert title not in res["agent_instruction"]


def test_unstocked_profile_still_reports_no_catalog_match(monkeypatch):
    """Genuine no-match must stay no_catalog_match even when the user also
    has down-ratings — the honesty branch must not mask the unstocked case."""
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w4"})
    res = rfm._build({"preferred_grapes": ["Assyrtiko"]}, None, None, 5, user_id="u1")
    assert res["result"] == "no_catalog_match"


def test_anonymous_user_skips_exclusion_entirely(monkeypatch):
    def _boom(uid):  # pragma: no cover
        raise AssertionError("preferences must not be queried for anonymous users")
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", _boom)
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id=None)
    assert set(_titles(res)) == {"Guvnor", "Bold Malbec"}


def test_exclusion_fetch_failure_is_swallowed(monkeypatch):
    """Exclusion is best-effort: a DB hiccup must degrade to 'no exclusion',
    never break the recommendation (project convention)."""
    def _boom(uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", _boom)
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id="u1")
    assert "error" not in res
    assert set(_titles(res)) == {"Guvnor", "Bold Malbec"}


def test_tool_closure_binds_user_id(monkeypatch):
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w2"} if uid == "u1" else set())
    tool = rfm.build_recommend_for_me_tool(_RED_PROFILE, user_id="u1")
    res = tool.func()  # LLM passes no identity — it's in the closure
    assert "Bold Malbec" not in _titles(res)


# ── №2 / №4: feedback aggregates ──────────────────────────────────────────────


_FB_ROWS = [
    {"wine_id": "w1", "wine_title": "Guvnor", "rating": "up",   "query_id": "q1", "created_at": "2026-07-01T10:00:00"},
    {"wine_id": "w1", "wine_title": "Guvnor", "rating": "up",   "query_id": "q2", "created_at": "2026-07-01T11:00:00"},
    {"wine_id": "w2", "wine_title": "Bold Malbec", "rating": "down", "query_id": "q1", "created_at": "2026-07-01T10:05:00"},
    {"wine_id": "w2", "wine_title": "Bold Malbec", "rating": "down", "query_id": "q3", "created_at": "2026-07-02T09:00:00"},
    {"wine_id": "w2", "wine_title": "Bold Malbec", "rating": "up",   "query_id": "q4", "created_at": "2026-07-02T10:00:00"},
    {"wine_id": "w9", "wine_title": None,          "rating": "down", "query_id": "q4", "created_at": "2026-07-02T12:00:00"},
]
_QL_ROWS = [
    {"id": "q1", "model": "anthropic/claude-haiku-4.5", "locale": "en"},
    {"id": "q2", "model": "anthropic/claude-haiku-4.5", "locale": "de"},
    {"id": "q3", "model": "openai/gpt-5.2",             "locale": "en"},
    {"id": "q4", "model": "openai/gpt-5.2",             "locale": "ru"},
]


def test_totals_and_overall_acceptance():
    agg = feedback_aggregates(_FB_ROWS, _QL_ROWS)
    assert agg["total_up"] == 3 and agg["total_down"] == 3
    assert agg["overall_acceptance"] == pytest.approx(0.5)


def test_per_wine_table_counts_and_down_share():
    per_wine = feedback_aggregates(_FB_ROWS, _QL_ROWS)["per_wine"]
    row = per_wine[per_wine["wine"] == "Bold Malbec"].iloc[0]
    assert (row["up"], row["down"], row["total"]) == (1, 2, 3)
    assert row["down_share"] == pytest.approx(0.67, abs=0.01)
    # sorted by total desc — the most-rated wine leads the purchasing signal
    assert per_wine.iloc[0]["wine"] == "Bold Malbec"


def test_wine_title_falls_back_to_id():
    per_wine = feedback_aggregates(_FB_ROWS, _QL_ROWS)["per_wine"]
    assert "w9" in set(per_wine["wine"])


def test_breakdowns_by_model_and_locale():
    agg = feedback_aggregates(_FB_ROWS, _QL_ROWS)
    by_model = agg["by_model"].set_index("model")
    assert by_model.loc["anthropic/claude-haiku-4.5", "acceptance"] == pytest.approx(0.67, abs=0.01)
    assert by_model.loc["openai/gpt-5.2", "acceptance"] == pytest.approx(0.33, abs=0.01)
    by_locale = agg["by_locale"].set_index("locale")
    assert by_locale.loc["en", "up"] == 1 and by_locale.loc["en", "down"] == 2


def test_trend_is_acceptance_by_date():
    trend = feedback_aggregates(_FB_ROWS, _QL_ROWS)["trend"]
    assert len(trend) == 2
    assert trend.iloc[0] == pytest.approx(2 / 3)   # 2026-07-01: 2 up / 1 down
    assert trend.iloc[1] == pytest.approx(1 / 3)   # 2026-07-02: 1 up / 2 down


def test_empty_and_missing_join_inputs():
    empty = feedback_aggregates([], [])
    assert empty["overall_acceptance"] is None
    assert empty["per_wine"].empty and empty["by_model"].empty
    # feedback without query_logs: totals still work, breakdowns just empty
    no_join = feedback_aggregates(_FB_ROWS, None)
    assert no_join["total_up"] == 3
    assert no_join["by_model"].empty and no_join["by_locale"].empty


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
