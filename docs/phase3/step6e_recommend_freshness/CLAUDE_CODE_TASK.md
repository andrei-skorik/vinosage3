# TASK: Phase 3, step 6e — recommend_for_me freshness + only-these-wines hardening

> For Claude Code. Two linked bugs from the human's step-5 smoke test.
> Root causes: (A) on a follow-up "recommend me something" turn the LLM
> skipped the recommend_for_me call entirely and re-presented wines from
> conversation history (no "Tools used" expander on that turn — zero tool
> calls), so the 👎-exclusion never executed; (B) recommend_for_me's SUCCESS
> payload — unlike pair_with_food's — carries no "recommend ONLY these"
> instruction, so the LLM supplemented the tool's 2 results with a 3rd wine
> from RAG context, bypassing the profile's price constraint (and that wine
> correctly got no feedback buttons, which is how the bug surfaced).
> The step-5 exclusion code itself is NOT implicated — it was never reached.

## Edits

### 1. `src/tools/recommend_for_me.py` — add agent_instruction to the SUCCESS path
In `_build`, the personalized success return (the one with `profile_used`)
gains an instruction, mirroring pair_with_food's pattern:

```python
        return {
            "profile_used": profile_used,
            "recommendations": recommendations,
            "count": len(recommendations),
            "agent_instruction": (
                f"Present ONLY these {len(recommendations)} wine(s), exactly as returned. "
                "Do NOT add, substitute, or re-present any other wine — not from the RAG "
                "context, not from earlier turns of this conversation. These results "
                "already reflect the user's saved taste profile AND their latest "
                "thumbs-up/thumbs-down feedback; earlier recommendations in the chat "
                "history are stale."
            ),
        }
```

Also extend the tool DESCRIPTION (in `build_recommend_for_me_tool`) with two
sentences appended to the existing text:
"Recommend ONLY the wines this tool returns — never supplement from RAG
context or conversation history. Call it FRESH on every recommendation
request, even a repeated one: results change whenever the user's profile or
👍/👎 feedback changes."

### 2. `src/agent.py` — strengthen the RECOMMENDATION QUERIES prompt block
Keep every existing rule verbatim (grounding guarantees). ADD to the
RECOMMENDATION QUERIES block:
- "For EVERY recommendation-type request you MUST call recommend_for_me in
  that same turn, even if you already recommended wines earlier in this
  conversation. The user's saved profile and 👍/👎 feedback can change
  between turns, so any previously shown recommendations are stale."
- "Never re-present wines from conversation history as recommendations
  without a fresh recommend_for_me call in the current turn."

### 3. Per-turn route nudge (deterministic backstop for the skipped call)
Where the agent node assembles the message list for a turn whose route is
`recommend` (you know the seam — `_build_messages` or the graph's agent_node
right after it), append ONE extra system message for that turn only:

```
Router: this turn is a recommendation request. You MUST call recommend_for_me
before answering. Recommendations shown earlier in this conversation are
stale — the user's profile or feedback may have changed since.
```

Implementation latitude on the exact seam (parameter on `_build_messages` vs
appending in the caller), but: recommend route only, one system message, no
change to any other route's messages, PAIRING block untouched.

### 4. Tests
- Extend `tests/test_step5_feedback.py` (or a small new file): the
  personalized success payload contains `agent_instruction` with "ONLY" and
  "stale"; the `no_profile_general` / `all_downrated` / `no_catalog_match`
  payloads are unchanged.
- A test at your chosen seam asserting: route `recommend` → the nudge system
  message is present in the assembled messages; route `general` and the
  pairing path → absent.
- `test_pair_with_food.py` and `test_recommend_for_me.py` must pass
  unmodified (the new instruction key is additive; if any legacy test
  asserts exact payload keys, report it — do not silently loosen it).

## Verification
1. `pytest` — full suite green.
2. `git diff --stat` — only recommend_for_me.py, agent.py (+ the seam file
   if separate), test files.
3. Confirm the PAIRING (CRITICAL) block and all NEVER/ALWAYS rules in the
   system prompt are byte-identical (grep/diff), per CLAUDE.md.
4. STOP for review.

## Human smoke test (after this fix — the exact failing scenario)
1. Profile: only Assyrtiko preferred (check whether a leftover max-price is
   set — remove or keep it consciously; report which).
2. "Recommend me something for tonight" → note Tools used: recommend_for_me
   called; buttons appear for EVERY presented wine (count matches).
3. 👎 all presented wines.
4. "Recommend me something for the night" again → EXPECT: Tools used present
   (fresh call); result excludes all 👎 wines — either the remaining
   Assyrtiko(s) or, if none remain, the honest all_downrated reply (one
   question, no wine names).

## Known residual (record in handoff)
Prompt+description+nudge is strong but still LLM-compliance, not a
structural guarantee. If a future smoke test catches the model skipping the
tool again despite all three layers, the next escalation is structural:
pre-invoking the bound recommend_for_me in the graph for the recommend route
and injecting its result as a tool message. Deliberately not done now —
bigger change to the ReAct loop than this bug justifies.
