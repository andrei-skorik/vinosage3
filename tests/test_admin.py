"""Tests for src/ui/admin.py's dev-panel model-override sentinel.

Bug fixed: st.selectbox always returns a concrete option, never None. Before
this fix, _render_dev_settings defaulted the selectbox to DEFAULT_MODEL and
assigned its return value straight to st.session_state.dev_model_override —
so merely unlocking the admin panel (rendering the selectbox once, without
touching it) silently started overriding every subsequent turn's model,
regardless of the user-facing Quick/In-Depth toggle in the sidebar
(app.py: `model = st.session_state.dev_model_override or (...)`).
_resolve_model_override is the pure mapping that closes this — it's tested
directly since the surrounding function is Streamlit-bound.
"""
from __future__ import annotations

from src.ui.admin import _NO_MODEL_OVERRIDE, _resolve_model_override


def test_sentinel_resolves_to_none():
    """Picking (or merely defaulting to) the sentinel must mean 'no
    override' — this is what keeps opening the panel a no-op."""
    assert _resolve_model_override(_NO_MODEL_OVERRIDE) is None


def test_real_model_choice_passes_through_unchanged():
    assert _resolve_model_override("anthropic/claude-haiku-4.5") == "anthropic/claude-haiku-4.5"
    assert _resolve_model_override("openai/gpt-5.2") == "openai/gpt-5.2"


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
