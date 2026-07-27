# VinoSage — Changelog

Full version history, moved out of `README.md` to keep that file focused on
what the project is and how to run it. See `PHASE3_HANDOFF.md` for the
detailed, step-by-step engineering record (decisions, defects, tests) behind
everything summarized here.

---

## What's new in v3.1

v3.0 shipped the features; v3.1 is what happened when a human ran a
structured smoke campaign against them — plus the top of the backlog.
**Eight real defects** were found on the live system (none reproducible by
the mocked unit suite — every one lived on a seam: LLM↔tool, catalog
data↔matcher, widget lifecycle↔rerun, UI↔profile), each fixed with a
regression test. Then four backlog items landed on top.

### New capabilities

| Capability | Detail |
|------------|--------|
| **Login survives refresh** | The Supabase refresh token is kept in a browser cookie (read natively via `st.context.cookies`, written by a staged one-shot JS snippet — `src/auth_persistence.py`). Tokens rotate on every restore; logout and "Forget me" clear the cookie. F5 now restores both the session *and* the durable chat in one go. |
| **True logout** | Logging out immediately resets to the pristine anonymous state — chat, profile, caches, metrics, even the age gate (`src/ui/session_reset.py`) — a privacy fix for shared machines. Explicit-list reset, never a blanket clear (the staged cookie deletion must survive it). |
| **GDPR-complete "Forget me"** | Now erases *everything*: taste profile, durable conversation thread, feedback rows, the login cookie, **and** the conversation history — `query_logs` rows are anonymized (`user_id → NULL`) and content-scrubbed (`'[erased]'`) rather than deleted, so the shared daily cost cap can't be reset by forgetting yourself. |
| **Multilingual food detection** | The 30 dishes added in v3.0's keyword-sync repair are now recognised in all four languages: explicit German singular/plural forms, and stem matching for Russian and Finnish (new `_FI_FOOD_STEMS`, mirroring the proven RU mechanism — "keittoon", "пельменям" and "Suppen" all route correctly). |
| **Voice spend in the cost cap** | Whisper transcription is billed per audio second; those costs are now recorded (`sql/10_stt_usage.sql`) and counted toward the €1/day cap alongside token spend — the two sources sum independently and degrade independently. |
| **Anon-thread housekeeping** | One admin-panel button sweeps the ephemeral `anon:*` checkpointer threads (safe by construction — anonymous sessions never read checkpoint state back). |
| **Delete My Account** | A separate, explicitly-confirmed button next to "Log Out" — permanently deletes the Supabase Auth account itself (`src/auth.py::delete_account`, Admin API), not just its data. Deliberately independent of "Forget me" (which never touches `auth.users`); `query_logs.user_id` has no cascade/set-null clause, so `erase_user_history` runs first to unblock the foreign key, then the account, durable thread, and login cookie are all cleared. |

### Smoke-campaign fixes (all with regression tests)

| Defect | Fix |
|--------|-----|
| LLM skipped `recommend_for_me` on repeat requests and re-presented stale wines from history | Three layers: an `agent_instruction` in the tool's success payload ("present ONLY these"), a hardened prompt block, and a per-turn router nudge |
| A 👎 could overwrite an explicitly preferred grape/style | §5.4 guard enforced: explicit positive preference wins over a single downvote |
| Toggling a rating off wiped manually-set preferences | Un-fold is now the exact inverse of fold — each fold records its delta (provenance in the feedback row's `reason` column) and toggle-off reverts exactly that |
| Typographic quotes in a catalog title ('White Ash') silently lost its feedback buttons | Title matching is typography-normalized on both sides |
| Whisper hallucinated "." on silent audio and burned a full LLM turn | Punctuation-only transcripts normalize to empty → the "couldn't hear anything" toast |
| `st.audio_input` showed a stale-upload error between voice turns | Widget-key rotation mounts a fresh recorder after each consumed recording |
| Anonymous 👍/👎 clicks wrote unattributable NULL-user rows | Feedback is login-gated end to end (UI hint + code gate), resolving a spec self-contradiction |
| An eval test gated on a pre-v2.0 tool choice and failed on legitimate ambiguity | Split: named-wines comparisons strictly require `compare_wines`; variety comparisons accept either tool, gating only on zero invented wines |

Plus the inherited v2.0 test-coverage gaps closed (locale-file parity with
placeholder checks, LangSmith-absence, cost-cap boundaries incl. pinned
fail-open, anonymous-feedback invariant, preference-extraction
false-positive regression) — **327 total unit tests**.

### New in v3.1: `sql/10_stt_usage.sql`

Apply after `sql/01`–`09` (and before deploying the voice-cost code — the
write path degrades silently without it):

| File | Creates |
|------|---------|
| `sql/10_stt_usage.sql` | `stt_usage` — per-transcription seconds + cost, summed into the daily cap |

---

## What's new in v3.0

v1.0 was a stateless recommender — every conversation started from zero.
v2.0 turned it into a **personal wine mentor** that teaches, remembers, and improves.
v3.0 makes it **durable and production-hardened**: conversations survive a
restart, you can talk to it instead of typing, and it never re-suggests a
wine you've already told it no to.

Five independent hardening/feature steps on top of v2.0 — durable memory, a
production reliability fix, a defense-in-depth repair, a new input modality,
and a smarter recommendation loop.

| Capability | Detail |
|------------|--------|
| **Durable conversation memory** | LangGraph `PostgresSaver` checkpointer (`src/checkpointer.py`) persists each logged-in user's chat log on Supabase Postgres, keyed by `thread_id = "user:{user_id}"`. Conversations survive browser refresh and server restarts. Anonymous users get an ephemeral `"anon:{session_id}"` thread by construction. `DATABASE_URL` absent or Postgres down → transparent fallback to an in-process `MemorySaver`, same behaviour as before this release. "Forget everything about me" now also erases the durable thread (`delete_thread`). |
| **Voice input** | Speak a question instead of typing: `st.audio_input` → Whisper Large V3 Turbo via OpenRouter's `/audio/transcriptions` endpoint (`src/transcribe.py`) — same API key, no new secret. The transcript is treated as pure data: it flows through the identical rate-limit → cost-cap → guard → router → agent pipeline as typed text, with no bypass. |
| **Feedback-aware recommendations** | `recommend_for_me` now excludes any wine the user currently has an active 👎 on, even if it matches every other profile dimension (`src/preferences.py::get_downrated_wine_ids`). If the user's own rejections are the *only* reason nothing matches, the agent says so honestly (`all_downrated`) instead of the misleading "nothing matches your taste." |
| **Admin feedback insights** | New admin-panel section: per-wine 👍/👎 counts + down-share (a purchasing signal for the shop) and an overall acceptance rate with a trend-by-date chart and breakdowns by model/locale — a free, continuous quality signal alongside the offline Ragas evals (`src/feedback_insights.py`). |
| **Rate-limit memory-leak fix** | `src/ratelimit.py`'s in-memory sliding-window dict used to grow one entry per browser session forever. A lazy periodic sweep now purges any session whose window has fully expired, bounding memory on long-lived deployments — with zero change to allow/block semantics. |
| **Anti-hallucination defense-in-depth repair** | The triple food-keyword defense (three deliberately independent copies, one per layer) had quietly drifted apart over time — 30 dishes (prawn, crab, soup, stew, scallop, …) were recognised by the catalog tool but not by the two evidence-filter layers or the router. Fixed and locked behind a sync test that fails the build on any future drift. |
| **Unit-test growth** | +47 new tests across the five v3.0 steps (checkpointer, rate-limit, keyword-sync, transcription, feedback exclusion/insights), all mocked — no real DB/LLM/audio calls required to run the suite. (v3.1 later grew the suite to 327.) |

### New environment variables (v3.0, all optional)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Supabase Postgres **Session pooler** connection string. Enables durable chat history; absent → in-memory only, app behaves exactly as before. |
| `TRANSCRIBE_MODEL` | Speech-to-text model override (default: `whisper-large-v3-turbo`). |

One-time setup for durable memory (run once, after setting `DATABASE_URL`):

```bash
python scripts/setup_checkpointer.py
```

This creates the LangGraph-managed `checkpoints` / `checkpoint_blobs` /
`checkpoint_writes` / `checkpoint_migrations` tables. It is intentionally
**not** a numbered `sql/` file — those tables are versioned by the
`langgraph-checkpoint-postgres` library itself, not by this project's schema.
No other v3.0 step added or changed any SQL; v3.1 later added `sql/10`
(`sql/01`–`09` remain untouched throughout, per project convention).

---

## What's new in v2.0

v1.0 was a stateless recommender — every conversation started from zero.
v2.0 turns it into a **personal wine mentor** that teaches, remembers, and improves.

| Capability | Detail |
|------------|--------|
| **LangGraph `StateGraph`** | Hand-wired 6-node graph replaces the black-box `create_agent`: `guard → load_preferences → router → retrieve → agent ↔ tools → extract_preferences`. Conditional retrieval — educational queries skip the catalog entirely. |
| **Long-term taste memory** | Per-user taste profile persisted in Supabase (`user_preferences`): preferred/disliked types, grapes, countries, styles, price range, expertise level. Survives restarts and devices. Anonymous users get a session-only profile. |
| **Personalised recommendations** | New `recommend_for_me` tool reads the stored profile and filters the catalog DataFrame by preference dimensions, ranks by overlap count, returns only in-stock wines. Non-catalog preferences are surfaced honestly, never invented. |
| **Wine education** | New `explain_wine_concept` tool fetches plain-language explanations from Wikipedia (no API key). Educational turns skip catalog retrieval; the agent never names catalog wines when answering a concept question. |
| **👍 / 👎 feedback loop** | Ratings on recommended wines fold back into the taste profile: 👍 adds type/grape/style to `preferred_*`; 👎 adds grape/style to `disliked_*` only if not already preferred. This is conditioning, not model training. |
| **Prompt- and memory-injection guard** | First graph node detects and blocks injection attempts before the LLM is called. Blocked attempts are logged to `security_events` with severity and matched rule. |
| **Dev / user separation** | Users see a *Quick / In-depth* speed toggle — no model names. Developers unlock a hidden admin panel with the real model registry, temperature slider, per-tool enable/disable, and a read-only system-prompt view. |
| **LangSmith observability** | Auto-instrumented via env vars (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`). Degrades gracefully when the key is absent — app runs identically without it. |
| **95 unit tests** | +26 new tests covering all v2.0 additions. All 11 original anti-hallucination tests (`test_pair_with_food.py`) pass unchanged — grounding guarantees from v1.0 are fully preserved. |

### v2.0 architecture

```
User (Streamlit UI)
       │
       ▼
  app.py  ──► rate_limit.py ──► guard: 10 req/min, €1/day cap
       │
       ▼
  graph.py  ──► LangGraph StateGraph
       │              │
       │         guard_node          (injection detection → security_events)
       │              │
       │         load_preferences    (reads user_preferences from Supabase)
       │              │
       │         router              (educate / recommend / compare / general)
       │              │
       │         retrieve (conditional — skipped for educate route)
       │              │
       │         agent_node  ◄──────────────────────────────────────────┐
       │              │                                                  │
       │              ├── filter_wines        (hard catalog constraints) │
       │              ├── pair_with_food      (dish → catalog pairings)  │
       │              ├── calculate_budget    (N bottles / €budget)      │
       │              ├── compare_wines       (fuzzy name match)         │
       │              ├── wine_stats          (aggregates)               │
       │              ├── explain_wine_concept (Wikipedia REST, NEW)     │
       │              └── recommend_for_me   (profile-conditioned, NEW) ─┘
       │              │
       │         extract_preferences  (detects taste signals → upserts profile)
       │
       ▼
  Supabase pgvector  ──► match_wines() RPC (HNSW cosine similarity)
       │
       ▼
  logging_db.py  ──► query_logs / tool_call_logs / token_usage /
                     recommendation_feedback / security_events
```

### New environment variables (v2.0, all optional)

| Variable | Description |
|----------|-------------|
| `LANGSMITH_TRACING` | Set `true` to enable LangSmith tracing |
| `LANGSMITH_API_KEY` | LangSmith API key (from smith.langchain.com) |
| `LANGSMITH_PROJECT` | Project name in LangSmith (default: `vinosage`) |
| `LANGSMITH_ENDPOINT` | Required for EU-region accounts: `https://eu.api.smith.langchain.com` |

### New database tables (v2.0)

Apply `sql/06` – `sql/09` after the existing `sql/01` – `sql/05`.
Run `sql/09_tool_logs_extend.sql` **first** (widens a CHECK constraint before
the new tools log anything).

| File | Creates |
|------|---------|
| `sql/06_preferences.sql` | `user_preferences` — per-user taste profile |
| `sql/07_security_events.sql` | `security_events` — injection audit log |
| `sql/08_feedback.sql` | `recommendation_feedback` — 👍/👎 per wine per query |
| `sql/09_tool_logs_extend.sql` | Widens `tool_call_logs.tool_name` CHECK for new tools |

### Key design decisions added in v2.0

| Decision | Reason |
|----------|--------|
| Preferences shape query/ranking only | Profile never produces a non-catalog wine — grounding guarantee extended to the memory layer |
| `recommend_for_me` built via factory closure | LLM never passes user identity; profile is pre-bound at request time |
| `extract_preferences` writes only on explicit signals | Casual wine mentions don't pollute the profile; sentence-boundary guard prevents trailing questions from being misread as preferences |
| Feedback fold excludes `type` from dislikes | One 👎 on a Malbec doesn't make the agent avoid all reds |
| LangSmith via env vars only, no `_require` | Tracing degrades gracefully — a missing key never crashes the app |
| `ragas` in `requirements-eval.txt`, not `requirements.txt` | Requires MS C++ Build Tools on Windows; optional eval-only dependency |
