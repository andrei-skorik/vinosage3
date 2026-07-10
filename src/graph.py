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
    # English — explicit & interrogative
    # recomend/recomends covers the common single-m typo alongside correct spelling.
    r"\b(recomm?end\w*|suggest)\b.{0,20}\b(me|for me|something)\b",
    # "Give/show/find/get me (some) recommendations" — imperative form where the
    # verb precedes "me" and "recommendations" follows with optional qualifiers.
    # m? tolerates the common single-m typo "recomendation(s)".
    r"\b(?:give|show|find|get)\s+me\b.{0,30}\brecomm?endations?\b",
    # "Recommend a sparkling wine under €25" — sentence-initial imperative without
    # "me". Anchored at ^ so "I don't recommend it" stays in general route.
    r"^\s*(?:please\s+)?recomm?end\b",
    r"\bwhat\s+should\s+i\s+(try|drink|buy)\b",
    # "What's a good/great/nice/decent/best X?" — a recommendation request,
    # not an educational one; must appear before the broad what's educate pattern.
    r"^\s*what'?s\s+(a\s+)?(good|great|nice|decent|best)\b",
    # Profile-explicit: user states they have or wants to use a saved profile.
    # "have" guard prevents matching "show/edit my profile"; "use" + "my saved"
    # guards are narrow enough that false positives are unlikely.
    r"\bhave\s+(?:a\s+|the\s+)?(?:saved\s+)?(?:taste\s+)?profile\b",
    r"\buse\s+(my\s+)?(saved\s+)?(taste\s+)?(profile|preferences?)\b",
    r"\bmy\s+saved\s+(taste\s+)?(profile|preferences?)\b",
    # Russian
    r"\bпосовет\w+\b", r"\bчто\s+(мне|бы)\s+(попробовать|выпить|взять|купить)\b",
    r"\bрекоменд\w+\s+мне\b",
    # "Порекомендуй мне" — prefix "по" pushes word boundary before "п", not "р",
    # so \bрекоменд\w+ above misses it; catch the full prefixed verb explicitly.
    r"\bпорекоменд\w+\b",
    # "Дай/покажи/подбери/найди мне рекомендации" — noun form, mirrors English fix.
    r"\b(?:дай|дайте|покажи|подбери|найди)\s+(?:мне|нам)\b.{0,30}\bрекомендаци\w+\b",
    r"\bесть\s+(сохранённый|сохраненный)\s+(вкусовой\s+)?профил\w+\b",
    r"\bиспользу\w+\s+(мой\s+)?(сохранённый|сохраненный|вкусовой)?\s*(профил|предпочтени)\w+\b",
    # German — "Was ist ein guter/großartiger/bester X?" must precede the broad
    # was ist educate pattern. \w* covers adjective inflections (gute/guter/gutes…).
    r"^\s*was\s+ist\s+(?:ein\s+)?(?:gut\w*|groß\w*|best\w*)\b",
    r"\bempfiehl\b|\bempfehle?\b|\bempfehlt\b", r"\bwas\s+soll\s+ich\s+(probieren|trinken|kaufen)\b",
    # "Gib/zeig mir Empfehlungen" — noun form not covered by verb patterns above.
    r"\b(?:gib|zeig|find|such)\s+mir\b.{0,30}\bempfehlungen\b",
    r"\bhabe\s+(ein\s+)?(gespeichertes?\s+)?geschmacksprofil\b",
    # Russian — "Что такое хорошее/лучшее X?" guard before the broad что такое pattern.
    r"\bчто\s+такое\s+(?:хорош\w+|лучш\w+|отличн\w+)\b",
    # Finnish — "Mikä on hyvä/mahtava/loistava/paras X?" mirrors the English
    # "What's a good/great/best X?" fix — must precede the broad mikä on educate pattern.
    r"^\s*mikä\s+on\s+(?:hyvä|mahtava|loistava|paras)\b",
    # Finnish — imperative/interrogative forms not covered by the "what's a good X?" guard.
    # suosittele = recommend (verb); mitä pitäisi/kannattaisi = what should I.
    r"\bsuosittele\b",
    r"\bmitä\s+(?:minun\s+)?(?:pitäisi|kannattaisi)\s+(?:juoda|kokeilla|ostaa|maistaa)\b",
    # "Anna minulle suosituksia" — imperative "give me recommendations" noun form.
    r"\banna\s+minulle\b.{0,30}\bsuosituksi\w+\b",
]

# Keywords that signal the previous assistant turn was in recommend/profile context.
# When these appear in the last assistant message AND the user reply is short (≤ 20 words),
# the reply is treated as a recommend-flow continuation so recommend_for_me stays available.
_RECOMMEND_CONTEXT_SIGNALS = [
    # English
    "taste profile", "saved profile", "preference", "personaliz", "personalid",
    "mood", "occasion", "red or white", "what do you enjoy", "what you like",
    "what you typically", "flavor", "flavour",
    # Russian
    "профил", "вкус", "предпочтени",
    # German
    "geschmack", "profil", "präferenz",
    # Finnish
    "makuprofiili", "suosikki", "mieltymys",
]


def _is_recommend_followup(query: str, history: list[dict[str, Any]] | None) -> bool:
    """Return True when the query is a short reply to a recommend-context assistant turn.

    Mirrors _is_food_query's history-scan: find the last assistant message and
    check whether it was asking about taste / profile. If so, any reply of ≤ 20
    words is treated as a follow-up so the agent still has recommend_for_me.
    Upper word-count cap prevents long independent queries from being
    mis-classified just because an old bot message happened to mention "profile".
    """
    if not history:
        return False
    if len(query.strip().split()) > 15:
        return False
    last_assistant = next(
        (m["content"].lower() for m in reversed(history) if m.get("role") == "assistant"),
        None,
    )
    if not last_assistant:
        return False
    return any(sig in last_assistant for sig in _RECOMMEND_CONTEXT_SIGNALS)


def _classify_route(query: str, history: list[dict[str, Any]] | None) -> str:
    """Educate / recommend / compare / general — SPEC §5.5.

    Explicit recommend patterns beat food-history context so that
    "Give me some recommendations" never mis-routes to general just because
    an earlier turn mentioned a food word.  A query that matches a recommend
    pattern AND contains a food keyword in the *current message* still goes to
    general (e.g. "Recommend a wine for my salmon dinner").
    """
    from src.agent import _is_food_query  # local import: src.agent imports this module

    q = query.lower()
    if any(re.search(p, q) for p in _RECOMMEND_PATTERNS):
        # Recommend pattern wins — unless the *current* query is itself a food
        # request (e.g. "Recommend wine for salmon"), in which case food wins.
        if not _is_food_query(query, None):
            return "recommend"
    if _is_food_query(query, history):
        return "general"
    # compare before educate: "Compare X and Y" must not accidentally match
    # educate patterns such as "difference between" before reaching this check.
    if " vs " in q or " versus " in q or re.search(r"^\s*compare\b", q):
        return "compare"
    if any(re.search(p, q) for p in _EDUCATE_PATTERNS):
        return "educate"
    # History-aware: short follow-up to a recommend-context assistant turn.
    # Checked last so explicit patterns above always win over heuristic.
    if _is_recommend_followup(query, history):
        return "recommend"
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

    profile = state.get("profile") or {}
    messages = _build_messages(
        state["query"],
        state.get("locale") or DEFAULT_LOCALE,
        state.get("history"),
        state.get("rag_context") or [],
        expertise_level=profile.get("expertise_level", "beginner"),
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
