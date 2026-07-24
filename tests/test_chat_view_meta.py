"""Regression tests for the wine-card metadata line crash.

Live crash: TypeError: sequence item 0: expected str instance, float found,
in render_feedback_buttons' `" · ".join(meta_parts)`. Root cause: wine dicts
built from a pandas DataFrame row (filter_wines.py/compare_wines.py's
`row.get("region")`, via df.iterrows()) return NaN — a TRUTHY float, not
None — for a missing string field, not None. The old
`w.get("region") or w.get("country")` fallback let that NaN straight through
into meta_parts, and `.join()` on a list containing a float raises.

_clean_meta_str is the fix — tested directly, plus one test that drives the
real render_feedback_buttons with a NaN-shaped wine dict to prove the exact
crash scenario no longer raises.
"""
from __future__ import annotations

import contextlib

import pytest
import streamlit as st

from src.ui.chat_view import _clean_meta_str, render_feedback_buttons


# ── _clean_meta_str: the pure fix ────────────────────────────────────────────


def test_clean_meta_str_passes_through_a_real_string():
    assert _clean_meta_str("Mendoza") == "Mendoza"


def test_clean_meta_str_rejects_nan_float():
    assert _clean_meta_str(float("nan")) is None


def test_clean_meta_str_rejects_none_and_empty_string():
    assert _clean_meta_str(None) is None
    assert _clean_meta_str("") is None


# ── render_feedback_buttons: the exact crash scenario, end to end ───────────


class _FakeColLabel:
    def markdown(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _isolate_session_state():
    st.session_state.clear()
    yield
    st.session_state.clear()


def _stub_widgets(monkeypatch):
    monkeypatch.setattr(st, "container", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(
        st, "columns",
        lambda *a, **k: (_FakeColLabel(), contextlib.nullcontext(), contextlib.nullcontext()),
    )
    monkeypatch.setattr(st, "button", lambda *a, **k: False)
    monkeypatch.setattr(st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(st.components.v1, "html", lambda *a, **k: None)


def test_render_feedback_buttons_survives_nan_region_and_country(monkeypatch):
    """The exact live repro: region AND country both NaN (pandas-missing),
    price_eur also NaN — must not raise."""
    _stub_widgets(monkeypatch)
    st.session_state["auth"] = {"user_id": "u-1"}
    st.session_state["_feedback_hydrated"] = True  # skip the DB hydration round-trip

    tool_calls = [{
        "tool_name": "filter_wines",
        "result": {"wines": [{
            "wine_id": "w-1", "title": "Test Wine",
            "region": float("nan"), "country": float("nan"), "price_eur": float("nan"),
        }]},
    }]

    render_feedback_buttons(tool_calls, query_id="q1", locale="en")  # must not raise


def test_render_feedback_buttons_falls_back_to_country_when_region_is_nan(monkeypatch):
    """Correctness, not just crash-avoidance: a NaN region must not shadow a
    perfectly good country value via the old truthy `or` fallback."""
    _stub_widgets(monkeypatch)
    markdown_calls: list[str] = []

    class _CapturingCol:
        def markdown(self, text, *a, **k):
            markdown_calls.append(text)

    monkeypatch.setattr(
        st, "columns",
        lambda *a, **k: (_CapturingCol(), contextlib.nullcontext(), contextlib.nullcontext()),
    )

    st.session_state["auth"] = {"user_id": "u-1"}
    st.session_state["_feedback_hydrated"] = True

    tool_calls = [{
        "tool_name": "filter_wines",
        "result": {"wines": [{
            "wine_id": "w-1", "title": "Test Wine",
            "region": float("nan"), "country": "Argentina", "price_eur": 12.5,
        }]},
    }]

    render_feedback_buttons(tool_calls, query_id="q1", locale="en")

    assert any("Argentina" in c and "€12.50" in c for c in markdown_calls)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
