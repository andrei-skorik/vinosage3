"""LangGraph StateGraph for the agent's turn-level pipeline (SPEC §5.1).

guard -> load_preferences -> router -> retrieve -> agent (<->tools) -> extract_preferences -> END

Phase 1: the surrounding pipeline is a hand-wired StateGraph; the ReAct
tool-calling loop itself still uses langchain.agents.create_agent inside the
`agent` node (SPEC §5.1 allows either — what matters is the surrounding
nodes exist). The retry->fallback chain ([model, model, FALLBACK_MODEL] with
a 2s sleep before the third attempt) lives here now, ported unchanged from
the previous direct-call implementation in src/agent.py.

`_build_messages` and `_is_food_query` are imported from src.agent and used
exactly as before — neither is modified by this module.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph

from src.config import CHAT_MODELS, DEFAULT_LOCALE, DEFAULT_MODEL, FALLBACK_MODEL
from src.guard import check_guard
from src.i18n import t
from src.llm import get_llm
from src.logging_db import log_security_event
from src.rag import RetrievedWine, retrieve
from src.tools.compare_wines import compare_wines
from src.tools.explain_wine_concept import explain_wine_concept
from src.tools.recommend_for_me import build_recommend_for_me_tool

log = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    # Turn input
    query:          str
    locale:         str
    model:          str
    temperature:    float
    disabled_tools: list[str]
    history:        list[dict[str, Any]] | None
    session_id:     str
    user_id:        str | None
    profile:        dict[str, Any]

    # Routing / retrieval
    route:       str
    rag_context: list[RetrievedWine] | None
    filter_used: dict[str, Any]

    # Guard
    blocked: bool

    # Memory write-back
    extracted_preferences: dict[str, Any]

    # Agent output
    answer:        str
    tool_calls:    list[dict[str, Any]]
    input_tokens:  int
    output_tokens: int
    model_used:    str
    status:        str
    error_code:    str | None


_EDUCATE_PATTERNS = [
    # English
    r"^\s*what\s+is\b", r"^\s*what'?s\b", r"^\s*who\s+is\b",
    r"\bexplain\b", r"\bdefine\b", r"\btell me about\b", r"\bdifference between\b",
    # Russian — "расскажи" intentionally omitted: "расскажи о мальбеке" is a
    # hybrid query (education + catalog) better served by the general route,
    # where the LLM has both explain_wine_concept AND catalog tools available.
    r"\bобъясни\b", r"\bчто\s+такое\b", r"\bчто\s+значит\b",
    r"\bкакая\s+разница\b", r"\bчем\s+отличаетс",
    # German
    r"\bwas\s+ist\b", r"\berkläre?\b", r"\bwas\s+bedeutet\b", r"\bunterschied\s+zwischen\b",
    # Finnish
    r"\bmikä\s+on\b", r"\bselitä\b", r"\bmitä\s+tarkoittaa\b", r"\bero\s+välillä\b",
]
_RECOMMEND_PATTERNS = [
    # English
    r"\b(recommend|suggest)\b.{0,20}\b(me|for me|something)\b",
    r"\bwhat\s+should\s+i\s+(try|drink|buy)\b",
    # "What's a good/great/nice/decent/best X?" — a recommendation request,
    # not an educational one; must appear before the broad what's educate pattern.
    r"^\s*what'?s\s+(a\s+)?(good|great|nice|decent|best)\b",
    # Russian
    r"\bпосовет\w+\b", r"\bчто\s+(мне|бы)\s+(попробовать|выпить|взять|купить)\b",
    r"\bрекоменд\w+\s+мне\b",
    # German
    r"\bempfiehl\b|\bempfehle?\b|\bempfehlt\b", r"\bwas\s+soll\s+ich\s+(probieren|trinken|kaufen)\b",
    # Finnish
    r"\bsuosittele\b", r"\bmitä\s+(minun\s+)?pitäisi\s+(kokeilla|juoda|ostaa)\b",
]


def _classify_route(query: str, history: list[dict[str, Any]] | None) -> str:
    """Educate / recommend / compare / general — SPEC §5.5.

    Food-pairing detection takes priority over everything else: pair_with_food
    must stay mandatory (edge case #18) regardless of how the rest of the
    query reads, so a food query always routes to 'general' (full retrieval +
    full tool set, unchanged behaviour from before the graph existed).
    """
    from src.agent import _is_food_query  # local import: src.agent imports this module

    if _is_food_query(query, history):
        return "general"
    q = query.lower()
    if any(re.search(p, q) for p in _RECOMMEND_PATTERNS):
        return "recommend"
    # compare before educate: "Compare X and Y" must not accidentally match
    # educate patterns such as "difference between" before reaching this check.
    if " vs " in q or " versus " in q or re.search(r"^\s*compare\b", q):
        return "compare"
    if any(re.search(p, q) for p in _EDUCATE_PATTERNS):
        return "educate"
    return "general"


def guard_node(state: AgentState) -> dict[str, Any]:
    verdict = check_guard(state["query"])
    if verdict["action_taken"] != "allowed":
        log_security_event(
            session_id=state.get("session_id") or "unknown",
            user_query=state["query"],
            event_type=verdict["event_type"],
            severity=verdict["severity"],
            action_taken=verdict["action_taken"],
            user_id=state.get("user_id"),
            locale=state.get("locale"),
            matched_rule=verdict["matched_rule"],
            model=state.get("model"),
        )
    if verdict["blocked"]:
        return {
            "blocked": True,
            "answer": t("error_off_topic", state.get("locale") or DEFAULT_LOCALE),
            "tool_calls": [],
            "rag_context": [],
            "filter_used": {},
            "status": "ok",
            "error_code": None,
        }
    return {"blocked": False}


def load_preferences_node(state: AgentState) -> dict[str, Any]:
    """Load this turn's taste profile into state.

    The actual Supabase read (src/preferences.get_preferences) needs the
    user's own session tokens to satisfy RLS (auth.uid() = user_id) — those
    tokens live in Streamlit's session state, not in this graph's state, so
    app.py reads the profile and hands it to run_agent(profile=...) before
    the graph runs. Anonymous users pass their session-only dict the same
    way. This node is therefore a pass-through by design, not a stub: {} for
    anonymous/new users, the already-resolved row otherwise.
    """
    return {"profile": state.get("profile") or {}}


def router_node(state: AgentState) -> dict[str, Any]:
    return {"route": _classify_route(state["query"], state.get("history"))}


def retrieve_node(state: AgentState) -> dict[str, Any]:
    """Multi-query + RRF retrieval, skipped entirely for the 'educate' route
    (SPEC §5.5) so a definition turn never gets catalog wines pushed into its
    context."""
    if state.get("route") == "educate":
        return {"rag_context": [], "filter_used": {}}

    if state.get("rag_context") is not None:
        # Caller (app.py's retrieval stepper) already retrieved this turn.
        return {}

    try:
        rag_result = retrieve(state["query"], locale=state.get("locale") or DEFAULT_LOCALE)
        return {"rag_context": rag_result.wines, "filter_used": rag_result.filter_used}
    except Exception as exc:
        log.warning("RAG retrieval failed: %s", exc)
        return {"rag_context": [], "filter_used": {}}


def _tools_for_route(route: str, profile: dict[str, Any], disabled_tools: list[str] | None = None) -> list:
    if route == "educate":
        # US-001 AC: educational turns must not trigger pair_with_food/filter_wines —
        # enforced structurally (no catalog tools available), not just by prompt wording.
        tools = [explain_wine_concept]
    elif route == "recommend":
        from src.agent import TOOLS
        tools = TOOLS + [build_recommend_for_me_tool(profile)]
    elif route == "compare":
        # compare_wines handles side-by-side catalog comparisons (fuzzy-matches
        # titles, so grape names like "Malbec" resolve to catalog wines).
        # explain_wine_concept is added so that variety/style comparisons
        # ("Compare Malbec and Merlot styles") can be answered educationally
        # without the LLM having to ask clarifying questions.
        tools = [compare_wines, explain_wine_concept]
    else:
        from src.agent import TOOLS
        tools = TOOLS

    if disabled_tools:
        # Admin dev panel per-tool toggles (SPEC §4.4) — default all enabled,
        # never user-facing.
        tools = [tl for tl in tools if tl.name not in disabled_tools]
    return tools


def agent_node(state: AgentState) -> dict[str, Any]:
    from src.agent import _build_messages  # local import: src.agent imports this module

    messages = _build_messages(
        state["query"],
        state.get("locale") or DEFAULT_LOCALE,
        state.get("history"),
        state.get("rag_context") or [],
    )
    tools = _tools_for_route(
        state.get("route") or "general", state.get("profile") or {}, state.get("disabled_tools")
    )

    model = state.get("model") or DEFAULT_MODEL
    if model not in CHAT_MODELS:
        model = DEFAULT_MODEL
    temperature = state.get("temperature")
    if temperature is None:
        temperature = 0.2  # end-user paths always default here; only the dev slider overrides

    tool_calls_log: list[dict[str, Any]] = []
    used_model = model

    for attempt, m in enumerate([model, model, FALLBACK_MODEL]):
        try:
            if attempt == 1:
                time.sleep(2)
            used_model = m
            llm = get_llm(m, temperature=temperature)
            agent = create_agent(llm, tools=tools)

            # invoke() (not stream) so each LLM call returns usage_metadata
            final_state = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 14},  # ~6 agent iterations
            )
            all_msgs = final_state["messages"]

            # Collect tool calls from all AI turns, keyed by tool_call_id so the
            # matching ToolMessage result can be attached to the right entry.
            tool_call_by_id: dict[str, dict[str, Any]] = {}
            for msg in all_msgs:
                if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls:
                        entry = {
                            "tool_name": tc["name"],
                            "arguments": tc["args"],
                            "result": None,
                        }
                        tool_call_by_id[tc["id"]] = entry
                        tool_calls_log.append(entry)

            # Attach each tool's actual return value to its call entry
            for msg in all_msgs:
                if isinstance(msg, ToolMessage):
                    entry = tool_call_by_id.get(msg.tool_call_id)
                    if entry is not None:
                        from src.agent import _parse_tool_message_content
                        entry["result"] = _parse_tool_message_content(msg.content)

            ai_msgs = [m for m in all_msgs if isinstance(m, AIMessage)]
            final_answer = ai_msgs[-1].content if ai_msgs else ""

            input_tokens = sum(
                (getattr(m, "usage_metadata", None) or {}).get("input_tokens", 0)
                for m in ai_msgs
            )
            output_tokens = sum(
                (getattr(m, "usage_metadata", None) or {}).get("output_tokens", 0)
                for m in ai_msgs
            )

            return {
                "answer": final_answer,
                "tool_calls": tool_calls_log,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model_used": used_model,
                "status": "ok",
                "error_code": None,
            }

        except Exception as exc:
            log.warning("Agent attempt %d with %s failed: %s", attempt + 1, m, exc)
            if attempt == 2:
                return {
                    "answer": "Sorry, I encountered an error. Please try again.",
                    "tool_calls": tool_calls_log,
                    "model_used": used_model,
                    "status": "error",
                    "error_code": "LLM_ERROR",
                }

    # unreachable
    return {"answer": "", "status": "error", "error_code": "INTERNAL"}


def extract_preferences_node(state: AgentState) -> dict[str, Any]:
    """Detect explicit taste signals in this turn and persist them.

    Only explicit, confident statements count (SPEC §5.3) — see
    src/preferences.detect_preference_signals. Logged-in users get an
    immediate service-role upsert (swallows failures, never blocks the
    chat reply); anonymous users get the detected signals back in
    extracted_preferences without any DB write — app.py merges those into
    the session-only profile dict, never the database (US-002 AC).
    """
    from src.preferences import detect_preference_signals, upsert_preferences

    signals = detect_preference_signals(state.get("query") or "", state.get("profile"))
    if not signals:
        return {"extracted_preferences": {}}

    user_id = state.get("user_id")
    if user_id:
        upsert_preferences(user_id, **signals)  # swallows internally; failure never blocks chat
    return {"extracted_preferences": signals}


def _route_after_guard(state: AgentState) -> str:
    return "blocked" if state.get("blocked") else "continue"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("guard", guard_node)
    graph.add_node("load_preferences", load_preferences_node)
    graph.add_node("router", router_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("agent", agent_node)
    graph.add_node("extract_preferences", extract_preferences_node)

    graph.set_entry_point("guard")
    graph.add_conditional_edges(
        "guard", _route_after_guard, {"continue": "load_preferences", "blocked": END}
    )
    graph.add_edge("load_preferences", "router")
    graph.add_edge("router", "retrieve")
    graph.add_edge("retrieve", "agent")
    graph.add_edge("agent", "extract_preferences")
    graph.add_edge("extract_preferences", END)
    return graph.compile()


_COMPILED_GRAPH = build_graph()


def run_via_graph(
    *,
    query: str,
    model: str,
    locale: str,
    history: list[dict[str, Any]] | None,
    rag_context: list[RetrievedWine] | None,
    filter_used: dict[str, Any],
    user_id: str | None,
    profile: dict[str, Any],
    session_id: str,
    temperature: float = 0.2,
    disabled_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Invoke the compiled graph for one turn. Returns the final AgentState dict."""
    initial_state: AgentState = {
        "query": query,
        "model": model,
        "locale": locale,
        "temperature": temperature,
        "disabled_tools": disabled_tools or [],
        "history": history,
        "rag_context": rag_context,
        "filter_used": filter_used,
        "user_id": user_id,
        "profile": profile,
        "session_id": session_id,
    }
    return _COMPILED_GRAPH.invoke(initial_state, config={"recursion_limit": 25})
