# VinoSage

## What this is

A personal AI wine mentor for an online wine shop.
Teaches wine concepts, remembers your taste and conversations across sessions
and restarts, recommends bottles from a live 1289-item catalog — grounded in
catalog evidence, never invented — and takes questions typed or spoken. Log in once — your session, taste
profile, and full conversation survive browser refreshes and server restarts.

Built on a hand-wired LangGraph `StateGraph` with 7 specialised tools,
multi-query RAG with RRF fusion, durable per-user taste memory and chat
history in Supabase Postgres, voice input via Whisper, and a 👍/👎 feedback
loop that both refines future recommendations and excludes wines you've
already rejected.

Supports 4 languages (EN / DE / RU / FI) end-to-end — including food-query
detection with German word forms and Russian/Finnish stem matching — and
includes rate limiting (leak-free),
daily cost caps, prompt-injection guard, LangSmith observability, and full
logging to Supabase — with an admin panel showing per-wine feedback and
acceptance-rate trends alongside the usual catalog/cost/security views.

Stack: Python · Streamlit · LangChain + LangGraph (+ Postgres checkpointer) ·
Supabase pgvector · OpenRouter (chat, embeddings, Whisper STT) · Pydantic v2 ·
rapidfuzz · pytest · LangSmith

![VinoSage chat screenshot](screenshots/chat.png)

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
false-positive regression) — **292 total unit tests**.

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
| **Unit-test growth** | +47 new tests across the five v3.0 steps (checkpointer, rate-limit, keyword-sync, transcription, feedback exclusion/insights), all mocked — no real DB/LLM/audio calls required to run the suite. (v3.1 later grew the suite to 292.) |

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

---

## Architecture

Current end-to-end pipeline (v2.0 `StateGraph` + all five v3.0 additions):

```
User (Streamlit UI)  ──► typed text ─┐
                     ──► 🎤 voice ────┼──► transcribe.py (Whisper via OpenRouter,
                                      │     transcript enters the pipeline as
                                      │     plain text — no bypass)
                                      ▼
  app.py  ──► rate_limit.py (sliding window, leak-free) ──► cost_cap: €1/day
       │
       ├──► checkpointer.py  (PostgresSaver — durable per-user thread,
       │      MemorySaver fallback when DATABASE_URL is absent)
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
       │              ├── explain_wine_concept (Wikipedia REST)          │
       │              └── recommend_for_me    (profile-conditioned,     ─┘
       │                                        excludes 👎-rated wines)
       │              │
       │         extract_preferences  (detects taste signals → upserts profile)
       │
       ▼
  Supabase pgvector  ──► match_wines() RPC (HNSW cosine similarity)
       │
       ▼
  logging_db.py  ──► query_logs / tool_call_logs / token_usage /
                     recommendation_feedback / security_events
       │
       ▼
  Admin panel  ──► feedback_insights.py (per-wine 👍/👎, acceptance rate,
                     trend, model/locale breakdowns)
```

**Stack:** Python 3.14 · Streamlit · LangChain 1.x + LangGraph (`langgraph-checkpoint-postgres`) · OpenRouter (chat, embeddings, Whisper STT) · Supabase (pgvector + Postgres checkpointer) · Pydantic v2 · rapidfuzz

---

## Prerequisites

| Tool | Notes |
|------|-------|
| Python 3.14+ | `python --version` |
| Supabase project | Free tier works — needs pgvector extension |
| OpenRouter API key | [openrouter.ai](https://openrouter.ai) |

---

## Quick Start

```bash
# 1. Clone and enter directory
git clone <repo-url>
cd vinosage

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env
# Edit .env — fill in all required values (see table below)

# 4. Apply database schema
python scripts/apply_sql.py

# 5. Seed catalog (1289 wines → embed)
python scripts/seed.py

# 6. Run the app
streamlit run app.py
```

The app opens at **http://localhost:8501**.
Default admin password is set in `.env` → `ADMIN_PASSWORD`.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in every value.

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | ✓ | OpenRouter API key |
| `SUPABASE_URL` | ✓ | Supabase project URL (`https://<ref>.supabase.co`) |
| `SUPABASE_ANON_KEY` | ✓ | Supabase anon/public key |
| `SUPABASE_SERVICE_KEY` | ✓ | Supabase service role key (used for DB writes) |
| `ADMIN_PASSWORD` | ✓ | Password for the admin panel in the sidebar |
| `OPENROUTER_MODEL` | – | Default chat model (default: `anthropic/claude-haiku-4.5`) |
| `EMBEDDING_MODEL` | – | Embedding model (default: `openai/text-embedding-3-small`) |
| `RATE_LIMIT_PER_MIN` | – | Max requests per minute per session (default: `10`) |
| `DAILY_COST_CAP_EUR` | – | Daily LLM cost cap in EUR (default: `1.00`) |

---

## Database Setup

Applies the numbered SQL files (`sql/01`–`11`, in order) to your Supabase
project via the Management API. Ordering matters three times: `sql/09` must
be live before the v2.0 tools log anything, `sql/10` before voice costs are
recorded, and `sql/11` after `scripts/setup_checkpointer.py` has created the
checkpointer tables at least once (it only adds RLS policies to tables that
must already exist).
Requires `SUPABASE_ACCESS_TOKEN` (create at https://supabase.com/dashboard/account/tokens)
and `SUPABASE_PROJECT_REF` (the `<ref>` in `https://<ref>.supabase.co`) — set both in `.env`.

```bash
python scripts/apply_sql.py
```

What it creates:
- `wines` table with pgvector column + HNSW index
- `query_logs`, `tool_call_logs`, `token_usage`, `rate_limit`, `catalog_audit` tables
- Row Level Security policies (anon: read-only; service role: all)
- `match_wines()` RPC for semantic search
- `flag_wine_embedding()` trigger (re-embeds on content change)
- `bulk_update_embeddings()` helper function
- `sql/11`: RLS + service-role-only policies on the LangGraph checkpointer
  tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
  `checkpoint_migrations`) — closes a Supabase Security Advisor finding;
  see that file's header comment for the full rationale

---

## Seed Catalog

```bash
# Full run: sync CSV → upsert → embed stale wines
python scripts/seed.py

# Preview only (no writes)
python scripts/seed.py --dry-run

# Sync catalog only, skip embedding
python scripts/seed.py --skip-embed
```

Embedding 1289 wines takes ~3 minutes (OpenRouter rate limits permitting).
Re-runs are idempotent — only wines with changed content are re-embedded.

---

## Running Tests

```bash
# Unit tests (no API calls — mocks only)
pytest

# Unit tests with verbose output
pytest -v

# Integration / eval tests (requires real API + seeded DB)
pytest -m integration

# All tests
pytest -m "integration or not integration"
```

Full eval suite (Ragas): `pip install -r requirements-eval.txt` (Linux/CI only; requires build tools on Windows).

Unit tests cover all 7 tools, RAG, i18n, the guard, taste-profile/preferences
logic, the durable checkpointer, rate limiting, food-keyword sync, voice
transcription, feedback exclusion/insights, auth persistence, session
reset, multilingual routing, and locale parity — 292 tests, ~25 s, all
mocked (no real DB/LLM/audio calls needed).
Integration eval tests (US-001..011 + 8 edge cases) are excluded by default.

---

## Deploy to Streamlit Cloud

1. Push the repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Set **Main file path**: `app.py`.
4. Open **Advanced settings → Secrets** and paste:

```toml
OPENROUTER_API_KEY   = "sk-or-v1-..."
SUPABASE_URL         = "https://<ref>.supabase.co"
SUPABASE_ANON_KEY    = "eyJ..."
SUPABASE_SERVICE_KEY = "eyJ..."
ADMIN_PASSWORD       = "your-password"
OPENROUTER_MODEL     = "anthropic/claude-haiku-4.5"
EMBEDDING_MODEL      = "openai/text-embedding-3-small"
RATE_LIMIT_PER_MIN   = "10"
DAILY_COST_CAP_EUR   = "1.00"

# Optional (v3.0) — omit either and the app degrades gracefully
DATABASE_URL         = "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
TRANSCRIBE_MODEL     = "whisper-large-v3-turbo"
```

5. Click **Deploy**.
6. If you set `DATABASE_URL`, run `python scripts/setup_checkpointer.py` once
   (locally, pointed at the same database) to create the checkpointer tables.

Streamlit Cloud sets these as environment variables, which `src/config.py` (and `src/checkpointer.py`/`src/transcribe.py` via `os.getenv`) read at runtime.

---

## Project Structure

```
vinosage/
├── app.py                    # Streamlit entrypoint
├── requirements.txt
├── pytest.ini
│
├── src/
│   ├── config.py             # All secrets + model registry
│   ├── catalog.py            # DataFrame cache (anon + service DB)
│   ├── ingest.py             # CSV normalisation + upsert
│   ├── embeddings.py         # OpenRouter embeddings + reconcile
│   ├── rag.py                # Multi-query + RRF retrieval
│   ├── llm.py                # LLM factory (OpenRouter via LangChain)
│   ├── agent.py              # System prompt, message building, retry helpers
│   ├── graph.py               # LangGraph StateGraph (guard→prefs→router→agent→extract)
│   ├── guard.py                # Prompt/memory-injection detection
│   ├── preferences.py          # Taste-profile read/write + provenance-tracked feedback fold + exclusion
│   ├── checkpointer.py         # PostgresSaver / MemorySaver durable chat memory (v3.0)
│   ├── transcribe.py           # Whisper STT via OpenRouter (v3.0; cost + silence handling v3.1)
│   ├── auth_persistence.py     # Login-across-refresh: cookie read/staged write (v3.1)
│   ├── feedback_insights.py    # Pure aggregation for admin feedback panel (v3.0)
│   ├── i18n.py               # t(key, locale) translation helper
│   ├── ratelimit.py          # Sliding-window rate limit + cost cap (leak-free)
│   ├── logging_db.py         # Observability writes to Supabase
│   ├── tools/
│   │   ├── filter_wines.py
│   │   ├── pair_with_food.py
│   │   ├── calculate_budget.py
│   │   ├── compare_wines.py
│   │   ├── wine_stats.py
│   │   ├── explain_wine_concept.py   # Wikipedia-backed education tool
│   │   └── recommend_for_me.py        # Profile-conditioned, excludes 👎-rated wines
│   └── ui/
│       ├── chat_view.py
│       ├── sidebar.py
│       ├── auth_view.py
│       ├── session_reset.py           # Logout → pristine anonymous state (v3.1)
│       └── admin.py                   # Includes per-wine feedback + acceptance-rate insights
│
├── scripts/
│   ├── apply_sql.py          # Apply SQL migrations via Management API
│   ├── seed.py               # Full catalog sync + embed
│   └── setup_checkpointer.py  # One-time durable-memory table setup (v3.0, human-run)
│
├── sql/
│   ├── 01_schema.sql
│   ├── 02_rls.sql
│   ├── 03_functions_triggers.sql
│   ├── 04_auth.sql
│   ├── 05_query_history.sql
│   ├── 06_preferences.sql
│   ├── 07_security_events.sql
│   ├── 08_feedback.sql
│   └── 09_tool_logs_extend.sql
│
├── locales/
│   ├── en.json
│   ├── de.json
│   ├── ru.json
│   └── fi.json
│
├── data/
│   └── WineDataset.csv       # 1289 wines (source of truth)
│
├── tests/
│   ├── conftest.py
│   ├── test_filter_wines.py
│   ├── test_pair_with_food.py
│   ├── test_calculate_budget.py
│   ├── test_compare_wines.py
│   ├── test_wine_stats.py
│   ├── test_rag.py
│   ├── test_guard.py
│   ├── test_preferences.py
│   ├── test_recommend_for_me.py
│   ├── test_explain_wine_concept.py
│   ├── test_routing.py
│   ├── test_expertise.py
│   ├── test_checkpointer.py       # v3.0 step 1
│   ├── test_ratelimit.py          # v3.0 step 2
│   ├── test_food_kws_sync.py      # v3.0 step 3
│   ├── test_transcribe.py         # v3.0 step 4
│   ├── test_step5_feedback.py     # v3.0 step 5
│   ├── test_hardening.py          # locale parity, LangSmith absence, cost-cap bounds
│   ├── test_feedback_anonymous.py # anon users never write feedback
│   ├── test_extract_preferences_regression.py
│   ├── test_title_matching.py     # typography-safe feedback buttons
│   ├── test_food_query_multilingual.py  # DE/RU/FI routing (v3.1)
│   ├── test_auth_persistence.py   # cookie flows + token rotation (v3.1)
│   ├── test_session_reset.py      # logout hygiene (v3.1)
│   ├── test_logging_db.py         # feedback deletion + history erasure (v3.1)
│   └── eval/
│       └── test_agent_eval.py  # integration, requires real API
│
└── docs/                      # Handoff record + per-step task briefs (Phase 3 / 3.1)
    ├── PHASE3_HANDOFF.md      # Full project record: decisions, smoke campaigns, backlog
    ├── phase3/                # Task briefs, steps 1–6h
    └── phase3.1/              # Task briefs, steps 1–4c
```

---

## Key Design Decisions

| Decision | Reason |
|----------|--------|
| Money stored as `INTEGER` cents | Avoids float rounding errors in price display/comparison |
| PostgREST vector strings | pgvector requires `"[0.1,...]"` string format, not a JSON array |
| RRF fusion (k=60) | Combines 4 query variants without amplifying noise |
| `precomputed_rag` param | Allows splitting retrieval from agent call for UI progress steps |
| Service role for all writes | RLS enforces read-only on chat path; admin writes audited |
| Logging never blocks chat | All `logging_db` calls swallow exceptions |
| `DATABASE_URL` / checkpointer via `os.getenv`, never `_require` | Durable memory is an enhancement, not a dependency — Postgres outage degrades to `MemorySaver`, chat still works |
| Thread ID = `user:{user_id}` / `anon:{session_id}` | Stable across refresh/restart for logged-in users; anonymous threads are ephemeral by construction, no separate code path needed |
| Feedback exclusion narrows, never invents | `recommend_for_me` only removes 👎-rated wines from the candidate set — grounding guarantee holds even as personalisation deepens |
| Three independent food-keyword copies + a sync test | Anti-hallucination defense-in-depth is deliberately not shared/merged across layers; the test (not code review) is what keeps them from drifting apart again |
| Refresh token in a cookie, read natively, written via staged JS | `st.context.cookies` works on the very first run (no component-mount races); writes are staged around reruns so the browser actually receives them; tokens rotate on every restore |
| Forget-me anonymizes history instead of deleting it | Hard-deleting `query_logs` would cascade into `token_usage` and let a user reset their contribution to the shared daily cost cap; anonymize + content-scrub erases the person, keeps the accounting |
| Fold provenance in the feedback row's `reason` column | Makes un-fold the exact inverse of fold with zero schema change — retracting a rating can never destroy manually-set preferences |
