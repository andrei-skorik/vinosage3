"""Tests for Phase 3, step 6e — recommend_for_me freshness + only-these-wines
hardening.

Two linked bugs from the human's step-5 smoke test:
(A) on a follow-up "recommend me something" turn the LLM skipped the
    recommend_for_me call entirely and re-presented wines from conversation
    history (the 👎-exclusion never executed because the tool was never
    called);
(B) recommend_for_me's SUCCESS payload carried no "recommend ONLY these"
    instruction (unlike pair_with_food's), so the LLM could supplement the
    tool's results with a wine from RAG context or history.

This file covers the three defense layers added: the tool's own
agent_instruction on success, the strengthened RECOMMENDATION QUERIES
system-prompt block, and the deterministic per-turn nudge message injected
for the recommend route only.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import src.preferences as prefs
import src.tools.recommend_for_me as rfm


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


# ── (B) recommend_for_me's SUCCESS payload gains an "ONLY these / stale" ────
# instruction, mirroring pair_with_food's pattern; every other result branch
# is unaffected.


def test_success_payload_gains_only_and_stale_instruction(monkeypatch):
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: set())
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id="u1")
    assert "result" not in res  # success path is the one WITHOUT a "result" key
    assert res["recommendations"]
    instr = res["agent_instruction"]
    assert "ONLY" in instr
    assert "stale" in instr


def test_no_profile_general_instruction_unchanged(monkeypatch):
    res = rfm._build({}, None, None, 5, user_id=None)
    assert res["result"] == "no_profile_general"
    assert "varied general picks" in res["agent_instruction"]
    assert "ONLY these" not in res["agent_instruction"]


def test_all_downrated_instruction_unchanged(monkeypatch):
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: {"w1", "w2"})
    res = rfm._build(_RED_PROFILE, None, None, 5, user_id="u1")
    assert res["result"] == "all_downrated"
    assert "thumbs-down" in res["agent_instruction"]
    assert "ONLY these" not in res["agent_instruction"]


def test_no_catalog_match_instruction_unchanged(monkeypatch):
    monkeypatch.setattr(prefs, "get_downrated_wine_ids", lambda uid: set())
    res = rfm._build({"preferred_grapes": ["Assyrtiko"]}, None, None, 5, user_id="u1")
    assert res["result"] == "no_catalog_match"
    assert "not stocked" in res["agent_instruction"]
    assert "ONLY these" not in res["agent_instruction"]


def test_tool_description_mentions_fresh_call_and_only_these():
    tool = rfm.build_recommend_for_me_tool(_RED_PROFILE, user_id="u1")
    assert "FRESH" in tool.description
    assert "ONLY the wines this tool returns" in tool.description


# ── (A) deterministic per-turn nudge for the recommend route ────────────────


def _system_messages(route: str | None) -> list[str]:
    from src.agent import _build_messages
    msgs = _build_messages(
        query="recommend me something for tonight",
        locale="en",
        history=None,
        rag_context=[],
        route=route,
    )
    return [m["content"] for m in msgs if m["role"] == "system"]


def test_recommend_route_gets_the_nudge_message():
    systems = _system_messages("recommend")
    assert any("Router: this turn is a recommendation request" in s and "stale" in s for s in systems)


def test_general_route_has_no_nudge_message():
    systems = _system_messages("general")
    assert not any("Router: this turn is a recommendation request" in s for s in systems)


def test_pairing_route_has_no_nudge_message():
    systems = _system_messages("compare")  # non-recommend route, mirrors the pairing path
    assert not any("Router: this turn is a recommendation request" in s for s in systems)


def test_no_route_has_no_nudge_message():
    """Default (route=None) — e.g. any call site that predates the route
    param — must not gain the nudge either."""
    systems = _system_messages(None)
    assert not any("Router: this turn is a recommendation request" in s for s in systems)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
