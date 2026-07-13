"""Tests for SPEC step 9 — the PostgresSaver checkpointer layer.

All tests run against the MemorySaver fallback (no DATABASE_URL / no DB
needed), because what we verify is OUR wiring, not the langgraph library:
graceful degradation, thread identity, append semantics, thread isolation,
serialization round-trip, and — critically — that the sacred layer-3 food
filter still operates on rehydrated history.
"""
from __future__ import annotations

import importlib
from typing import Annotated, Any, TypedDict  # noqa: F401 — module globals needed for
# get_type_hints() to resolve the locally-defined MiniState TypedDict below
# (Python 3.14 PEP 649 lazy annotations evaluate against module globals, not
# the enclosing function's locals).

import pytest

from src.graph import _append_chat_log  # noqa: F401 — same reason as above; the real reducer under test


# ── Graceful degradation (edge case #3-style: app must run without the URL) ──


def test_memory_fallback_when_no_database_url(monkeypatch):
    """Without DATABASE_URL the checkpointer must be an in-process MemorySaver
    and the module import must not raise (same contract as LangSmith)."""
    import src.checkpointer as cp

    monkeypatch.setattr(cp, "DATABASE_URL", "", raising=True)
    monkeypatch.setattr(cp, "_checkpointer", None, raising=True)

    saver = cp.get_checkpointer()
    assert type(saver).__name__ in ("MemorySaver", "InMemorySaver")
    assert cp.is_durable() is False


def test_memory_fallback_on_broken_database_url(monkeypatch):
    """A present-but-broken DATABASE_URL must degrade, never crash startup."""
    import src.checkpointer as cp

    monkeypatch.setattr(cp, "DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/x", raising=True)
    monkeypatch.setattr(cp, "_checkpointer", None, raising=True)

    saver = cp.get_checkpointer()  # must not raise
    assert saver is not None
    # restore singleton for other tests
    monkeypatch.setattr(cp, "_checkpointer", None, raising=True)


# ── Thread identity ───────────────────────────────────────────────────────────


def test_thread_id_stable_for_logged_in_user():
    from src.checkpointer import resolve_thread_id

    a = resolve_thread_id("user-123", "sess-A")
    b = resolve_thread_id("user-123", "sess-B")  # new browser session, same user
    assert a == b == "user:user-123"


def test_thread_id_ephemeral_for_anonymous():
    from src.checkpointer import resolve_thread_id

    a = resolve_thread_id(None, "sess-A")
    b = resolve_thread_id(None, "sess-B")
    assert a != b
    assert a.startswith("anon:") and b.startswith("anon:")


# ── Append semantics + thread isolation via the reducer ──────────────────────
# We exercise the real reducer through a minimal compiled StateGraph with a
# MemorySaver, mirroring how src/graph.py wires chat_log — without importing
# src.graph itself (which pulls in the full LLM/tool stack).


def _build_minigraph():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, StateGraph

    class MiniState(TypedDict, total=False):
        chat_log: Annotated[list[dict[str, Any]], _append_chat_log]
        query: str

    def noop(state):
        return {}

    g = StateGraph(MiniState)
    g.add_node("noop", noop)
    g.set_entry_point("noop")
    g.add_edge("noop", END)
    return g.compile(checkpointer=MemorySaver())


def test_chat_log_accumulates_across_turns_on_same_thread():
    graph = _build_minigraph()
    cfg = {"configurable": {"thread_id": "user:alice"}}

    graph.invoke({"query": "turn 1"}, config=cfg)
    graph.update_state(cfg, {"chat_log": [{"role": "user", "content": "hi"},
                                          {"role": "assistant", "content": "hello"}]})
    graph.invoke({"query": "turn 2"}, config=cfg)
    graph.update_state(cfg, {"chat_log": [{"role": "user", "content": "more"},
                                          {"role": "assistant", "content": "sure"}]})

    log = graph.get_state(cfg).values.get("chat_log") or []
    assert [m["content"] for m in log] == ["hi", "hello", "more", "sure"]


def test_chat_log_isolated_between_threads():
    graph = _build_minigraph()
    cfg_a = {"configurable": {"thread_id": "user:alice"}}
    cfg_b = {"configurable": {"thread_id": "user:bob"}}

    graph.invoke({"query": "a"}, config=cfg_a)
    graph.update_state(cfg_a, {"chat_log": [{"role": "user", "content": "alice-only"}]})
    graph.invoke({"query": "b"}, config=cfg_b)

    log_b = graph.get_state(cfg_b).values.get("chat_log") or []
    assert log_b == []  # Bob never sees Alice's log


# ── Serialization round-trip ──────────────────────────────────────────────────


class _FakeWine:
    """Duck-typed stand-in for rag.RetrievedWine."""
    def __init__(self):
        self.wine_id = "w-1"
        self.title = "The Guv'nor"
        self.similarity = 0.87
        self.payload = {
            "type": "Red", "grape": "Tempranillo", "country": "Spain",
            "style": "Rich & Juicy", "price_eur_cents": 1179,
            "description": "A perfect pairing for beef short ribs.",
        }


def test_serialize_rehydrate_roundtrip_preserves_getattr_contract():
    from src.checkpointer import rehydrate_chat_entry, serialize_chat_entry

    entry = {
        "role": "assistant",
        "content": "Try The Guv'nor.",
        "sources": [_FakeWine()],
        "query_id": "q-1",
        "user_query": "recommend me a red",
    }
    flat = serialize_chat_entry(entry)
    # must be plain data (checkpoint-safe)
    assert isinstance(flat["sources"][0], dict)
    assert flat["query_id"] == "q-1"

    back = rehydrate_chat_entry(flat)
    w = back["sources"][0]
    # the exact access pattern used by chat_view / _agent_history / CSV export
    assert getattr(w, "title") == "The Guv'nor"
    assert getattr(w, "payload", {}).get("price_eur_cents") == 1179
    assert getattr(w, "wine_id") == "w-1"


def test_sacred_layer3_filter_operates_on_rehydrated_sources():
    """Regression anchor: after a refresh, _agent_history's food filter
    (_history_source_ok — the third anti-hallucination layer) must behave on
    rehydrated PersistedWine objects exactly as on live RetrievedWine objects.
    """
    app = importlib.import_module("app")
    from src.checkpointer import rehydrate_chat_entry, serialize_chat_entry

    beef_wine = _FakeWine()  # description confirms beef pairing
    choc_wine = _FakeWine()
    choc_wine.title = "Sweet Night"
    choc_wine.payload = dict(choc_wine.payload)
    choc_wine.payload["description"] = "Notes of dark chocolate and a creamy texture."

    persisted = [
        serialize_chat_entry({"role": "user", "content": "what goes with beef?"}),
        serialize_chat_entry({
            "role": "assistant",
            "content": "Here are options.",
            "sources": [beef_wine, choc_wine],
        }),
    ]
    messages = [rehydrate_chat_entry(m) for m in persisted]

    history = app._agent_history(messages, current_query="is the beef one the only option?")
    joined = "\n".join(m["content"] for m in history if m["role"] == "system")
    # beef pairing is trigger-anchored -> survives the filter
    assert "The Guv'nor" in joined
    # tasting-note chocolate (no pairing trigger) must NOT pass as evidence
    assert "Sweet Night" not in joined


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
