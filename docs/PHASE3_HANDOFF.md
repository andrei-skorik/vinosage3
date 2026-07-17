# VinoSage 2.0 — Phase 3 Handoff Document

> **For the next Claude session.** Read this alongside `CLAUDE.md` and `docs/SPEC.md`.
> Tracks Phase 3 (5 steps total, per `docs/phase3/`). This document records what
> has been built, non-obvious design decisions, and known gaps for this phase.

---

## Current state

- **Branch:** `main`
- **Phase 3 steps completed:** 5 of 5 core steps, plus eight post-completion
  hardening steps (6, 6b, 6c, 6d, 6e, 6f, 6g, 6h) — PostgresSaver checkpointer,
  ratelimit memory-leak fix, food-keyword sync guard, voice input (Whisper
  STT), feedback exclusion + admin insights, inherited Phase-2 gap tests,
  the anonymous-feedback DB-write gate, a Whisper silence-hallucination fix,
  a voice-widget stale-error fix, recommend_for_me freshness + only-these-wines
  hardening, the §5.4 fold guard fix, typography-safe title matching (the
  'White Ash' incident), and delta-provenance un-fold.
- **Committed & pushed** (all on `origin/main`, confirmed local `HEAD` ==
  `origin/main`):
  - `5660294` — steps 1–5 (`feat(phase3): durable checkpointer, rate-limit
    fix, food-kw sync, voice input, feedback exclusion`)
  - `eaf5177` — steps 6+6b (`test(phase3): hardening — inherited gap tests,
    anon-feedback gate, env hygiene`)
  - `8750ab2` — step 6c (`fix(voice): normalize punctuation-only Whisper
    hallucinations to empty`)
  - `d1fb9a5` — step 6d (`fix(voice): rotate audio_input widget key to
    clear stale-upload error`)
  - `b1c8793` — step 6f (`fix(preferences): stop 👎 from overwriting an
    explicit preferred grape/style`)
  - `e1d1724` — step 6g (`fix(chat-view): typography-normalize title
    matching to fix missing feedback buttons`)
  - `49c3be2` — step 6h (`fix(preferences): make un-fold the exact inverse
    of fold, not a blanket wipe`)
  - `cc98236` — step 6e (`fix(recommend): call recommend_for_me fresh every
    turn and stop supplementing results`)
- **Test count:** 249 passed, 0 xfailed, 21 deselected (integration/eval) —
  see "Step 6" section below for the count at each intermediate step.
- **Remaining:** none — Phase 3 (+ hardening) is fully complete. The entire
  human-only checklist below is now **DONE** except the optional git tag
  (all real-world smoke tests — voice, step-5 feedback incl. the 7-step
  campaign, 6b anonymous UI, 6f/6h data cleanup — passed after the fixes in
  this document). See "Smoke-test campaign summary" for the full results.
  Remaining work is only the "Known accepted gaps" and "Backlog" sections
  below (both deliberately deferred, not blocking).

---

## Phase 4 — final summary (steps 1–4c)

All six Phase 4 tasks are complete, committed, and human-smoke-tested. Final
test count: **292 passed**, 22 deselected (integration/eval), up from 249 at
the end of Phase 3.

| Step | What | Commit | Tests after |
|------|------|--------|-------------|
| 1 | Split the wrongly-scoped `test_us004_compare_wines_uses_tool` into two correctly-scoped compare-tool eval tests | `aced670` (combined with step 2) | 251 |
| 2 | Multilingual routing coverage for the 30 food nouns (DE literal forms, RU stem extension, new FI stem mechanism) | `aced670` | 267 |
| 3 | STT cost accounting (`sql/10_stt_usage.sql` + `log_stt_usage`) folded into the daily cost cap; `anon:*` checkpoint-thread housekeeping (`sweep_anon_threads` + admin button) | `fd0451f` | 272 |
| 4 | Login persistence via a browser-component cookie manager — **superseded**, its own human smoke test failed before any commit (cookie never written; see step 4b) | *(never committed standalone — folded into `d5e6d7b`)* | 279 (uncommitted) |
| 4b | Redesign: native `st.context.cookies` read + staged one-shot `_emit_cookie_js` write, dependency removed | `d5e6d7b` (combined with step 4's surviving pieces — `refresh_session`, the UI call sites) | 283 |
| 4c | Logout session hygiene (`reset_to_anonymous()`, incl. the `_auth_restore_done` self-defeat fix found during this step) + Forget-me history erasure (`erase_user_history`, anonymize-not-delete) | `3a36a3e` | 292 |

See each step's own section below for full detail; "Known accepted gaps" §3
and the Backlog carry the cross-references.

---

## Step 1 — PostgresSaver checkpointer (`docs/phase3/step1_checkpointer/`)

**Status:** Done and verified in production (Supabase Session pooler,
`DATABASE_URL` set, `scripts/setup_checkpointer.py` run once by the human).

**What it is:** Durable conversation state via LangGraph's `PostgresSaver`,
replacing `st.session_state`-only chat history for logged-in users. See
`src/checkpointer.py` for the design rationale (thread identity, graceful
degradation to `MemorySaver`, serialization contract).

**Verified:**
- `pytest` green (159 passed) including `tests/test_checkpointer.py` and
  unchanged `test_pair_with_food.py`.
- Import with `DATABASE_URL` unset → `MemorySaver` fallback, no crash.
- Import with `DATABASE_URL` set (post `setup_checkpointer.py`) →
  `is_durable() == True`, `PostgresSaver` active.
- Manual smoke test (human): logged-in user, 2 messages, F5 refresh →
  chat history restored correctly from Postgres after logging back in.

**Files:** `src/checkpointer.py` (new), `src/graph.py` (chat_log channel +
reducer + compile with checkpointer + `append_chat_log`/`get_thread_chat_log`/
`delete_thread` helpers), `src/agent.py` (`thread_id` passthrough), `app.py`
(thread resolution + rehydration + append after logging), `src/ui/sidebar.py`
(GDPR `delete_thread` hook), `scripts/setup_checkpointer.py` (new, human-run
only), `tests/test_checkpointer.py` (new).

**Adaptation vs. reference:** `tests/test_checkpointer.py`'s `_build_minigraph()`
originally defined a local `TypedDict` with `Annotated[...]` referencing names
imported only inside the function. Python 3.14's lazy-annotation evaluation
(PEP 649) resolves those against module globals, not the enclosing function's
locals, so it raised `NameError` on this project's Python version. Fixed by
hoisting the relevant imports (`Annotated`, `Any`, `TypedDict`,
`_append_chat_log`) to module level — no change to test logic/assertions.

---

## Step 2 — ratelimit.py memory-leak fix (`docs/phase3/step2_ratelimit/`)

**Status:** Done. `src/ratelimit.py`'s `_windows` dict grew one entry per
`session_id` forever. Fixed with a lazy periodic sweep (`_purge_stale_sessions`,
piggybacked on `check_rate_limit`, runs at most once per 300 s, drops sessions
whose newest timestamp has aged past the 60 s window). Rate-limit semantics
unchanged (verified byte-identical: same allow/block decisions, same
`retry_after_s`). New `tests/test_ratelimit.py` (8 tests, time monkeypatched).

---

## Step 3 — food-keyword drift fix + sync guard (`docs/phase3/step3_food_kws/`)

**Status:** Done. The triple anti-hallucination defense's three independent
food-noun copies had drifted: layer 1 (`pair_with_food._FOOD_NOUNS`, canonical,
64 items) had gained 30 nouns over time (prawn, crab, soup, stew, scallop,
etc.) that layers 2 (`agent._FOOD_KWS`) / 3 (`app._HIST_FOOD_KWS`) and the
routing set (`agent._FOOD_QUERY_KWS`) never received — so for those 30 foods,
routing didn't detect a food query and the layer-2/3 evidence filters never
engaged. Defense-in-depth was silently down to one layer for ~30 common dishes.

**Fix (variant A — approved, no merge/import across layers):**
- Hoisted `agent._FOOD_KWS` from a local var inside `_build_messages` to
  module scope (needed so the sync test can import it; zero logic change).
- Added the 30 missing nouns to `agent._FOOD_KWS`, `app._HIST_FOOD_KWS`, and
  `agent._FOOD_QUERY_KWS` (English section only). `"cake"` and `"dessert"`
  still intentionally absent from all three evidence sets.
- New `tests/test_food_kws_sync.py` (copied as-is, 8 tests): set equality
  across the three evidence layers with a drift diff on failure, cake
  absent-from-evidence/present-in-routing, routing ⊇ evidence, the three
  trigger regexes identical (pattern + flags), and behavioral regressions
  pinning that "prawns"/"stew" now engage the evidence filter.
- `src/tools/pair_with_food.py` (layer 1, canonical) untouched — confirmed via
  `git diff` (empty).

~~**Known gap (explicitly out of scope for step 3):** the 30 new nouns are
English-only.~~ **RESOLVED (Phase 4, step 2)** — see below.

---

## Phase 4, step 2 — multilingual routing coverage for the 30 food nouns (`docs/phase3.1/step2/`)

**Scope:** routing detection only (`agent._FOOD_QUERY_KWS` DE/FI sections +
`agent._RU_FOOD_STEMS`, plus a new `agent._FI_FOOD_STEMS`). The three
evidence sets (`_FOOD_NOUNS`, `_FOOD_KWS`, `_HIST_FOOD_KWS`) match English
catalog text and were **not** touched — verified both by the existing
`test_food_kws_sync.py` (unchanged, 8/8 pass) and a direct re-assertion in
the new test file.

**Investigation findings (as the task required, before any edit):**
- **DE:** confirmed plain lowercase word-members of `_FOOD_QUERY_KWS`,
  matched by `_in_fqkws` — exact match, or the trailing `"-s"` strip meant
  for English plurals (irrelevant to German morphology). German plurals
  therefore needed **explicit literal forms**, not stemming.
- **FI:** same mechanism as DE — plain exact-match members of
  `_FOOD_QUERY_KWS`. The existing code comment ("stem forms cover nominative
  + partitive") does not reflect reality — there was no actual Finnish stem
  mechanism, so heavily-inflected forms (partitive, genitive, illative, ...)
  of the pre-existing FI words were already silently missed before this
  step, and would have stayed missed for the 30 new nouns too. **No FI stem
  mechanism existed**, so per the task's own instruction ("prefer stems for
  Finnish too" if one existed), a new one was introduced: `_FI_FOOD_STEMS` +
  `_has_fi_food()`, structurally identical to `_RU_FOOD_STEMS`/`_has_ru_food`
  (prefix/`startswith` match on words ≥3 chars). The pre-existing FI words
  already in `_FOOD_QUERY_KWS` were deliberately left untouched — in scope
  for this step is the 30 new nouns' coverage only, not a general FI-vocabulary
  redo (avoids an unreviewed behavior change to already-working coverage).
- **RU:** confirmed `_RU_FOOD_STEMS`/`_has_ru_food` already do genuine
  prefix/stem matching (6-case coverage via `startswith`) — additions here
  just extend the existing stem set, same mechanism, no new function needed.

**Vocabulary actually added** (human-curated list, adapted to the mechanism
found; nothing dropped — all proposed words were judged low-risk):
- **German** (literal singular/plural pairs added to `_FOOD_QUERY_KWS`):
  `pudding, mousse, fondue, brownie/brownies, tarte, törtchen, brot,
  brioche, fladenbrot, nudel/nudeln, knödel, klöße, teigtaschen,
  garnelen (garnele singular already present), krabben (krabbe singular
  already present), tintenfisch, kalmar, oktopus, krake,
  jakobsmuschel/jakobsmuscheln, wachtel/wachteln, fasan, burger, suppe/suppen,
  eintopf, gulasch, ragout, chili, tapas`.
- **Finnish** (new `_FI_FOOD_STEMS`, prefix-matched): `vanukas/vanukka`
  (pudding), `mousse, fondue, brownie, torttu/tortu` (tart), `leipä/leivä`
  (bread), `nuudeli` (noodle), `katkarapu/katkarav` (prawn), `rapu/ravu`
  (crab), `kalmari` (squid), `mustekala` (octopus), `kampasimpuk` (scallop),
  `viiriäi` (quail), `fasaani` (pheasant), `burgeri/hampurilai` (burger),
  `keitto/keito` (soup), `muhenno` (stew), `chili, tapas`. **Deliberately
  skipped:** `pata` (stew/pot — too polysemous, per the human's own note).
- **Russian** (added to `_RU_FOOD_STEMS`; суп/краб/кальмар/осьминог/
  гребешк/креветк/бургер/рагу verified already present, not duplicated):
  `пудинг, мусс, фондю, брауни, тарт, хлеб, бриош, лепешк/лепёшк, лапш,
  пельмен, вареник, клецк/клёцк, перепел, фазан, чили, тапас`.

**Red-first confirmed:** all three probe assertions
(`_is_food_query("Welcher Wein passt zu Suppe?", None)`,
`_is_food_query("Какое вино подойдет к пельменям?", None)`,
`_is_food_query("Mikä viini sopii keittoon?", None)`) returned `False`
before the edit, `True` after.

**Tests:** new `tests/test_food_query_multilingual.py` (16 tests) — 4
positive + 1 negative-control test per language (each including one
inflected/plural form: "Suppen", "пельменям", "keittoon" and others), plus
one direct re-assertion that the three English evidence sets are still
equal to each other and contain none of the new non-English words.

**Verified:** full suite green, **267 passed** (was 251, +16 exactly).
`test_food_kws_sync.py` unchanged (8/8 pass). `git diff --stat`: only
`src/agent.py` + `tests/test_food_query_multilingual.py` (new) +
this handoff file.

---

## Phase 4, step 3 — STT cost accounting + anon-thread housekeeping (`docs/phase3.1/step3/`)

**Scope:** two independent, previously-deferred gaps from Step 4's voice
input build, closed in one task: (A) transcription spend was invisible to
the daily cost cap; (B) anonymous checkpoint threads accumulate forever with
no cleanup path.

**Part A — STT cost accounting:**
- New `sql/10_stt_usage.sql` (generated only, **not applied** — per project
  rule, only the human applies SQL via the Supabase SQL Editor). Table:
  `id, created_at, session_id, user_id (FK auth.users, on delete set null),
  model, seconds, cost_eur_micros (>= 0)`; index on `created_at desc`;
  service-role-only RLS policy, matching the existing `token_usage` pattern.
- `src/transcribe.py`: success dict gains `cost_eur_micros` (OpenRouter's
  `usage.cost`, USD, converted 1:1 to EUR-equivalent integer micros, same
  convention as `token_usage`).
- `src/logging_db.py`: new `log_stt_usage(*, session_id, user_id, model,
  seconds, cost_eur_micros)` — insert-only, swallows exceptions (project
  convention: logging never blocks the chat/voice turn).
- `app.py`: voice-input block now calls `log_stt_usage` for **every**
  consumed outcome that returned usage — including empty-transcript silence,
  which still billed seconds — not just successful transcripts. Uses the
  already-resolved `_auth_now` for `user_id` (`None` for anonymous, matching
  the `stt_usage.user_id` nullable FK).
- `src/ratelimit.py::get_daily_cost_micros`: now sums `token_usage` +
  `stt_usage` independently, each in its own try/except. A failure in one
  source (e.g. `sql/10` not yet applied) degrades to under-counting that
  source only — it does **not** zero out the other, healthy source.

**Part B — anonymous checkpoint thread housekeeping:**
- `src/checkpointer.py`: new `sweep_anon_threads() -> int`. No-ops (returns 0)
  on `MemorySaver`. On `PostgresSaver`, reads distinct `anon:*` thread_ids
  directly from the library-owned `checkpoints` table (read-only, via the
  existing connection pool), then deletes each one through the official
  `delete_thread` API only — never mutates the library's tables directly.
  Two independent layers of `anon:` enforcement: the SQL `WHERE thread_id
  LIKE 'anon:%'` filter, plus a Python-side `startswith("anon:")` re-check
  after the fetch — so a `user:*` thread can never be swept even if the SQL
  filter were ever loosened by a future edit. Safety argument for why this is
  behaviorally invisible even for a live anonymous session: anonymous chat
  lives in `st.session_state`, `chat_log` is never appended to the durable
  log for anonymous users, and every other per-turn channel is simply
  overwritten on the graph's next invoke — there is nothing durable for an
  anonymous session to lose.
- `src/ui/admin.py`: manual "Clean up anonymous threads" button in the
  Developer settings panel (`_render_dev_settings`), after the LangSmith
  status caption — spinner while sweeping, then a toast with the deleted
  count. Manual/admin-triggered by design; Streamlit Cloud has no cron. An
  on-startup opportunistic sweep remains a possible future refinement, not
  implemented (see Backlog).
- New locale keys in all four `locales/*.json`: `admin_sweep_anon_button`,
  `admin_sweep_anon_done` (`{count}` placeholder).

**Tests:** `tests/test_transcribe.py` extended (2 tests updated to assert
`cost_eur_micros`), `tests/test_hardening.py` (+2: STT+token sum, STT-failure
degrades gracefully), `tests/test_checkpointer.py` (+3: no-op on
`MemorySaver`, deletes only `anon:*` via a fake `PostgresSaver`/pool/cursor
fixture, total failure returns 0 without raising).

**Verified:** full suite green, **272 passed** (was 267, +5 unit tests; the
transcribe test updates didn't add new test count, just assertions).
`git diff --stat sql/` shows only the new, untracked `sql/10_stt_usage.sql` —
`sql/01`–`09` untouched.

**⚠️ Deploy reminder: `sql/10_stt_usage.sql` must be applied via the Supabase
SQL Editor before this code reaches production.** Until then, `log_stt_usage`
silently no-ops (exception swallowed) and `get_daily_cost_micros` under-counts
by the STT share — degraded, not broken, but worth doing before relying on
the cap for real spend control.

**Human-only checklist — ✅ DONE, confirmed by the human:**
1. ✅ `sql/10_stt_usage.sql` applied via the Supabase SQL Editor before deploy.
2. ✅ Smoke test passed: a voice question produced a row in `stt_usage`;
   admin analytics rendered fine; the sweep button showed a toast with a
   count; a logged-in user's thread survived an F5 refresh (still `user:*`,
   untouched by the sweep).

---

## Phase 4, step 4 — login persistence across browser refresh (`docs/phase3.1/step4/`, superseded by step 4b below)

**Scope:** the last of the four Phase 4 tasks, run alone per the task's own
instruction (auth-sensitive). Closes known-gap §3: `st.session_state.auth`
died on F5 even though the durable chat (step 9) survived and reloaded once
the user logged back in.

**Original design (step 4, since replaced — see step 4b):** a browser-
component-based cookie manager package (pinned in `requirements.txt`),
chosen at the time over a less-maintained alternative. **The human smoke
test failed at the very first check: no cookie was ever written** (verified
in Chrome and Edge DevTools; no server-side errors — the failure was
browser-side). Root cause and full redesign in "Phase 4, step 4b" below;
the package has been removed entirely.

---

## Phase 4, step 4b — fix login persistence (cookie never saved)

**Root cause (confirmed in code before any fix):** the step-4 cookie
manager was a browser COMPONENT — its write only runs the underlying JS if
the component's HTML actually reaches the browser in a *completed* script
run. `src/ui/auth_view.py`'s login/register/logout handlers all called the
cookie write and then `st.rerun()` in the SAME run — the run is aborted
before the component ever renders, so the write is silently lost every
time. **Same failure class as the Phase-2 sidebar bug** that led to the
`_pending_profile_update` staging pattern (`src/ui/sidebar.py`) — a fix that
was already in this exact codebase and should have been the template from
the start. Additionally, the component's read side spun up one
`st.components.v1.html` call per read — ×15-per-rerun deprecation-warning
spam in the logs for a component API Streamlit is removing.

**Redesign — read natively, write via staged one-shot JS:**
- **Read:** `st.context.cookies` (native `Mapping`, no component at all) —
  synchronous and populated on the very first script run, since cookies
  arrive in the HTTP request headers. This deletes the entire
  component-mount quirk the step-4 version had to work around with a
  guarded rerun and its session flag — none of that exists anymore.
- **Write/clear:** `_emit_cookie_js(value)`, a zero-height
  `st.components.v1.html` snippet that sets `document.cookie` directly (one
  definition, in `src/auth_persistence.py`). Belt-and-braces validation
  rejects any token containing `'`, `"`, `;`, or whitespace before it's
  interpolated into the JS string literal (the token is ours — a
  Supabase-issued JWT — but the check costs nothing and closes the
  injection question outright). Still uses `st.components.v1.html` (no
  non-deprecated raw-HTML API exists in the pinned Streamlit for this), but
  now fires only on the rare write/clear action instead of on every single
  read on every rerun — deprecation-warning volume drops from ×15/rerun to
  effectively zero in normal use.
- **Staging around reruns (the project's own pattern, reused deliberately):**
  login/register success calls `save_token(token)` → stages
  `st.session_state["_pending_cookie"] = token`; logout / forget-me call
  `clear_token()` → stages the empty-string clear sentinel. Both still
  `st.rerun()` immediately after, exactly as before — that's fine now,
  because nothing tries to emit JS in the run that's about to be aborted.
  `emit_pending_cookie()`, called at the very top of `app.py::main()` (before
  `try_restore_session()`), pops the stage and calls `_emit_cookie_js` on the
  FOLLOWING run, which then runs to completion untouched by any further
  rerun.
- **Restore is the one path that emits directly:** `try_restore_session`
  never calls `st.rerun()` itself, so on a successful restore it calls
  `_emit_cookie_js(rotated_token)` immediately, in the same run — no staging
  needed there, since there's no rerun to race.
- **Dependency removed:** the step-4 cookie-manager package is gone from
  `requirements.txt` and uninstalled locally; confirmed via grep that
  neither its name nor its class name appears anywhere in the codebase.

**Files (this step):**
- `src/auth_persistence.py` (rewritten) — `read_token` (now
  `st.context.cookies.get(...)`), `_emit_cookie_js` (new, the only
  write/clear path), `save_token`/`clear_token` (now stage instead of
  writing inline — same public names, so `auth_view.py`/`sidebar.py`'s call
  sites needed zero changes), `emit_pending_cookie` (new), `try_restore_session`
  (simplified — no more mount-quirk/guarded-rerun logic).
- `app.py` — `emit_pending_cookie()` added at the very top of `main()`,
  immediately before `try_restore_session()`.
- `requirements.txt` — the step-4 package removed; net diff against the
  pre-step-4 baseline is now empty (added then removed the same line).
- `src/auth.py`, `src/ui/auth_view.py`, `src/ui/sidebar.py` — unchanged from
  step 4 (the `refresh_session` addition and the `save_token`/`clear_token`
  call sites all still apply as-is under the new implementation).

**Tests:** `tests/test_auth_persistence.py` rewritten for the new seams
(monkeypatch `st.context.cookies` for reads, capture `_emit_cookie_js` calls
for writes) — 11 tests: the same core restore/rotation/invalid-token/no-cookie
scenarios as step 4 (rotation write-back is still the critical assertion,
now phrased as "the rotated token is emitted"), plus new coverage for the
staging mechanism itself (`save_token`/`clear_token` stage and are consumed
exactly once by `emit_pending_cookie` on the next call, not re-emitted on a
third), and direct tests of `_emit_cookie_js` (unsafe-character rejection,
real HTML output for set vs. clear, exception-swallowing).

**Verified:**
- Full suite green, **283 passed** (was 279, +4 net — 7 step-4 tests
  replaced by 11 new ones).
- Grep: the step-4 package name and its cookie-manager class name appear
  nowhere in the codebase (code, tests, or `requirements.txt`); exactly one
  `_emit_cookie_js` definition (`src/auth_persistence.py`).
- `git diff --stat`: `src/auth_persistence.py` (rewritten), `app.py`,
  `src/auth.py`, `src/ui/auth_view.py`, `src/ui/sidebar.py`,
  `tests/test_auth_persistence.py` (rewritten) — `requirements.txt` shows no
  diff at all against the pre-step-4 baseline (net zero), nothing in `sql/`,
  RLS, the age gate, or `config._require`.

**Human smoke test — ✅ ALL PASSED, confirmed by the human** (component/
browser behavior can't be unit-tested; this was the decisive check after
step 4's own smoke test had failed):
1. ✅ Log in → send a message → F5 → still logged in AND chat restored in
   one go → F5 again (rotation check) → still logged in. DevTools confirmed
   the cookie visible, `SameSite=Lax`, and its VALUE CHANGING between the
   two refreshes (rotation proof — the critical check for this step).
2. ✅ Log out → F5 → logged out; cookie gone from DevTools.
3. ✅ "Forget everything about me" → F5 → logged out, no profile, no chat.
4. ✅ Private window: anonymous flow unchanged, no cookie written.
5. ✅ Full browser restart → still logged in.

---

## Phase 4, step 4c — logout session hygiene + Forget-me history erasure

Two adjacent defects surfaced by the (otherwise passing) step-4b smoke test.
Neither touches the cookie mechanics (`src/auth_persistence.py`'s
`_emit_cookie_js`/read paths) — those were confirmed working and were not
modified.

### Defect A — logout left the previous user's chat/profile on screen

Privacy issue on shared machines: after "Log out", `st.session_state.auth`
and the cookie were cleared, but `messages`, feedback-rating caches, profile
caches, session metrics, etc. stayed rendered until a manual refresh.
Required behavior (per an explicit product-owner call): logout resets
*immediately* to the pristine anonymous first-visit state — age gate
included.

**Fix:** new `src/ui/session_reset.py::reset_to_anonymous()` — an
**explicit-list** clear (never `st.session_state.clear()`), called from both
the logout handler (`src/ui/auth_view.py`) and the forget-me handler
(`src/ui/sidebar.py`), after their existing deletions/staging. Clears:
`messages`, `auth`, `age_confirmed` (the age-gate flag), `_chat_rehydrated`;
profile caches (`_prefs_cache`, `_pending_profile_update`, the 9 taste-profile
multiselect/radio widget keys, the 2 price `number_input` keys, the 3
avatar-upload UI keys); `_history_cache` ("My conversations", Defect B);
feedback-rating caches (`wine_ratings`, `wine_ratings_loaded`); session
metrics (`session_tokens_in/out`, `session_cost_micros`, `last_latency_ms`);
voice keys (`_last_voice_digest`, `_voice_widget_gen`); `queued_prompt`.
Enumerated by grepping every `st.session_state[...]` write in `src`/`app.py`
(see the module for the exact list — `_KEYS_TO_CLEAR`). Generates a fresh
`session_id` (new anonymous rate-limit window + a new, unreachable `anon:*`
thread). Ends with `st.rerun()`.

**Deliberately NOT cleared** (this is the load-bearing part of the fix, not
an omission):
- `locale` — a device/language preference, not identity.
- `_catalog_options_cache` — non-personal, expensive to rebuild.
- `_welcome_picks_*` — non-personal cosmetic cache (random example
  prompts), locale-scoped rather than identity-scoped; not enumerated at all.
- **`_pending_cookie`** — the caller (logout/forget-me) just staged a
  cookie write/clear in this exact key; wiping it here means
  `emit_pending_cookie()` never sees it on the next run, the JS delete never
  fires, and the real browser cookie survives — the user would look logged
  out in this tab but auto-restore on the next F5.
- **`_auth_restore_done`** — not just left alone, but **force-set to
  `True`**. This is a second, sharper instance of the same trap, found
  during this step (not called out by the task): Streamlit's own docs
  describe `st.context.cookies` as reflecting only "the initial request" —
  it stays frozen at whatever the browser sent when the tab's session first
  opened, for the rest of that tab's life, regardless of any
  `document.cookie` write issued via JS since. A user who logged in via the
  form this session (never through cookie-restore) may still have this flag
  unset; leaving it merely untouched would let `try_restore_session()` fire
  again on the very next rerun and — using that stale, frozen cookie
  snapshot — silently re-authenticate the just-erased user. For logout this
  would only fail (Supabase's `sign_out()` already revoked the token
  server-side), but **forget-me never calls `sign_out()`** — the Supabase
  session stays fully valid — so without forcing this flag, "Forget
  everything about me" would be silently undone in the same click.

**Not in scope, flagged for a future look:** `admin_unlocked`,
`dev_model_override`, `dev_temperature`, `dev_tools_enabled` are untouched by
`reset_to_anonymous()` — the task's own enumeration didn't name the dev/admin
panel as a category, so they were left alone rather than guessed at. Worth
noting: if an admin overrides `dev_temperature` away from 0.2 and then logs
out without re-locking the panel, the NEXT anonymous user's chat would run
at that overridden temperature (`app.py` applies `dev_temperature`
regardless of `admin_unlocked`) — a latent, adjacent violation of the
"temperature stays 0.2 for all end-user paths" invariant on a shared
machine. Not fixed here; added to the Backlog below.

### Defect B — "Forget everything about me" left "My conversations" intact

The history feature (`src/ui/auth_view.py::render_history_view`) reads
`query_logs` by `user_id`; forget-me never touched those rows, so the full
conversation history survived — and reloaded — even after re-login.

**Approved semantics — anonymize + scrub, never hard-delete.** Hard-deleting
`query_logs` would cascade (`on delete cascade`, `sql/01`) into
`token_usage`, silently shrinking `ratelimit.get_daily_cost_micros()`'s
running total — i.e. forget-me would let a user reset their own
contribution to the shared daily cost cap (spend → forget → spend again).

**Fix:** new `src/logging_db.py::erase_user_history(user_id) -> bool`:
```sql
update query_logs
   set user_id = NULL, user_query = '[erased]', final_answer = '[erased]'
 where user_id = :uid;

update security_events
   set user_id = NULL
 where user_id = :uid;
```
Identity unlinked, content erased, numeric cost rows (`token_usage`, keyed
by `query_id` not `user_id`) intact and still counted by the cap. Returns
`False` (never raises) on any failure, so the forget-me UI shows its
existing generic error instead of a false success. Wired into the sidebar's
forget-me handler alongside the existing `delete_all_feedback` call. The
"My conversations" session cache (`_history_cache`) is cleared by Defect A's
`reset_to_anonymous()`.

**GDPR honesty note (as flagged by the task, recorded here):**
`tool_call_logs`/`token_usage` retain non-personal operational rows linked
to now-anonymous query ids — never personal on their own (tool arguments,
token counts), so left as-is. `security_events.user_id` is explicitly nulled
by `erase_user_history` for the same reason `query_logs` needs it done
explicitly: its FK is `on delete set null`, but that only fires if the
`auth.users` row itself is deleted — forget-me does not delete the account,
only the user's data. The event **content** (`user_query`, `matched_rule`,
`action_taken`, etc.) is intentionally left intact even after the user_id
nulling — those rows exist for security audit (detecting abuse patterns),
not personalisation, and unlinking identity is judged sufficient for GDPR
purposes here without destroying the audit trail. Additionally: **anonymous
`query_logs` rows** (welcome-chip clicks, private-window sessions — anything
logged with `user_id = NULL` from the start) retain their readable
`user_query`/`final_answer` text permanently; `erase_user_history` only ever
matches `WHERE user_id = :uid`, so these rows are never touched by any
user's forget-me. This is accepted, not a gap: those rows were never linked
to an identity in the first place — they are unattributable by
construction, with no `user_id` to reverse-engineer or erase-by — so they
fall outside forget-me's scope entirely.

**Tests:** new `tests/test_session_reset.py` (7 tests) — `reset_to_anonymous`
clears every enumerated key, rotates `session_id`, preserves `locale`/
`_catalog_options_cache`, calls `st.rerun()`; the two self-defeat
regressions (`_pending_cookie` survives, `_auth_restore_done` is forced
`True` even when it started `False`); and one heavy-stub wiring test driving
`sidebar.render_taste_profile()`'s forget-me "yes" branch end-to-end,
asserting `delete_preferences`/`delete_thread`/`delete_all_feedback`/
`erase_user_history`/`clear_token` all fire and `reset_to_anonymous` fires
last. `tests/test_logging_db.py` (+2): `erase_user_history` issues both
UPDATEs with the right `eq(user_id=...)` filter; a DB failure returns
`False` without raising.

**Verified:** full suite green, **292 passed** (was 283, +9 exactly — 7 in
`test_session_reset.py`, 2 in `test_logging_db.py`). `git diff sql/` —
empty (this is a data UPDATE via the service-role client, no schema change;
`sql/01`–`09` untouched, confirmed). `git diff --stat`: `src/logging_db.py`,
`src/ui/auth_view.py`, `src/ui/sidebar.py`, `tests/test_logging_db.py`,
plus new `src/ui/session_reset.py` and `tests/test_session_reset.py` —
`src/auth_persistence.py` untouched, as required.

**Human smoke test — ✅ ALL PASSED, confirmed by the human:**
1. ✅ Log in → chat → Log out → IMMEDIATELY: age gate shown, no chat, no
   profile visible; F5 → still logged out (the `_pending_cookie`/
   `_auth_restore_done` traps check held); DevTools: cookie gone.
2. ✅ Log in as the same user → chat history from BEFORE the logout was
   still there (logout does not erase server-side history — only forget-me
   does).
3. ✅ "Forget everything about me" → confirm → immediate pristine state; on
   re-login: My conversations EMPTY; profile empty; Supabase spot-check
   confirmed the user's old `query_logs` rows have `user_id NULL` and
   `user_query = '[erased]'`; today's cost total in the admin analytics was
   unchanged by the erasure (the anonymize-not-delete design holding as
   intended).

---

## Step 4 — voice input via Whisper (`docs/phase3/step4_voice/`)

**Status:** Done, pending human smoke test with a real mic + real API call.

**What it is:** Users can speak a question via `st.audio_input` instead of
typing. Audio is transcribed by Whisper Large V3 Turbo through OpenRouter's
`/audio/transcriptions` endpoint (same base URL + API key as chat/embeddings —
no new secret). The transcript is treated as pure data: it feeds `prompt` in
`app.py` and flows through the exact same pipeline as typed text (rate limit →
cost cap → guard node → router → agent). No bypass, no special-casing.

**Files:** `src/transcribe.py` (new — `transcribe_audio()`: 15 s timeout + 1
retry after 2 s, `_ERR(code, msg)` on failure, never raises; pre-validates
empty/oversized (>25 MB) audio without a network call; passes locale as
Whisper's `language` hint), `tests/test_transcribe.py` (new, 10 tests, network
monkeypatched), `src/config.py` (`TRANSCRIBE_MODEL` constant, `os.getenv`
default `whisper-large-v3-turbo`), `app.py` (voice widget + digest-dedup +
rate-limit pre-check + `voice_prompt` feeding the normal `prompt` resolution),
`.env.example` (`TRANSCRIBE_MODEL=`), all four `locales/*.json` (5 new
`voice_*` keys + one appended `help_body` line).

**Verified:**
- Full suite green (185 passed), including the 10 new transcription tests and
  unchanged `test_pair_with_food.py`.
- All four locale files parse and contain the 5 new keys.
- `git diff src/guard.py` empty — guard logic untouched.
- Prompt pre-flight order in `app.py` (`rate_limit → cost_cap → …`) unchanged;
  `voice_prompt` only ever populates the same `prompt` variable typed input
  does, so it hits every guard identically.
- No real API calls made during this step (per task instructions) — human
  validated the endpoint separately via curl before this step started.

**Known gaps (recorded per task, not fixed):**
- ~~Transcription spend (billed per audio second via OpenRouter's `usage.cost`)
  is **not** counted toward the €1/day `DAILY_COST_CAP_EUR` cap — `token_usage`
  is query-keyed and no query exists yet at transcription time. The sliding-
  window rate limit is the effective throttle in the meantime. Future option:
  a new `stt_usage` table (new numbered `sql/` file) folded into the cap.~~
  **RESOLVED (Phase 4, step 3).** New `sql/10_stt_usage.sql` (generated only —
  **must be applied via the Supabase SQL Editor before deploy**, else
  `log_stt_usage` silently no-ops and the cap under-counts, degraded not
  broken). `src/transcribe.py` now returns `cost_eur_micros`; `app.py` logs it
  via new `src/logging_db.py::log_stt_usage`; `src/ratelimit.py::
  get_daily_cost_micros` sums `token_usage` + `stt_usage` independently (a
  failure in one source degrades to under-counting, never zeroes the other).
  See "Phase 4, step 3" section for full detail.
- A voice turn consumes **2 rate-limit slots** (one pre-check before
  transcription, one in the normal prompt pre-flight) — accepted, documented
  in the code comment at the voice-widget call site in `app.py`.
- **(Step 6c fix)** Punctuation-only Whisper hallucinations on silent audio
  normalized to empty — see the Step 6 section below (6c) for the full entry;
  moved there since it's a hardening fix, not part of the original step 4 build.

**Human-only checklist (not yet done — pass to the human):**
1. Manual smoke test with real mic + real API: record "recommend a red wine"
   → transcript appears as the chat message → normal answer. Repeat with a
   RU/DE/FI phrase in the matching locale. Then speak a prompt-injection
   phrase ("ignore previous instructions") → confirm the guard's canned reply
   fires and a `security_events` row is written — proving pipeline parity
   between voice and typed input.
2. Optional: set `TRANSCRIBE_MODEL` in secrets only if a non-default STT model
   is wanted.

---

## Step 5 — feedback exclusion + admin insights (`docs/phase3/step5_feedback/`)

**Status:** Done, pending human smoke test (recommendation flow + admin tab).
This was the last of the 5 Phase 3 steps.

**What it is:** Three features approved for this step:
- **№1 — exclusion list:** `recommend_for_me` never re-recommends a wine the
  user currently has an active 👎 on, even if it matches the profile on every
  other dimension. Includes an honesty branch (`all_downrated`): when the
  user's own rejections are the *only* reason nothing matches, the agent says
  that plainly instead of the misleading "nothing matches your taste."
- **№2 — per-wine feedback table (admin):** 👍/👎 counts + down-share per
  wine, a purchasing signal for the shop.
- **№4 — acceptance rate (admin):** share of 👍 among all ratings, overall +
  trend by date + breakdown by model/locale — a continuous online quality
  metric complementing the offline Ragas evals.
- Out of scope (backlog, human decision): cold-start prior (№3), collaborative
  filtering (№5), profile-drift detection (№6).

**Files:** `src/tools/recommend_for_me.py` (new `_excluded_wine_ids(user_id)`;
`_build(...)` splits `base_hard` from `hard_mask = base_hard & ~excluded`,
adds the `all_downrated` branch checked before the unstocked-dimension check;
`_diverse_picks(...)` gains `excluded`; `build_recommend_for_me_tool(profile,
user_id=None)`), `src/preferences.py` (new `get_downrated_wine_ids(user_id)`,
service-role read via `get_service_db()`, latest-rating-wins per wine),
`src/graph.py` (`_tools_for_route(...)` and `agent_node` thread `user_id`
through to the tool builder), `src/feedback_insights.py` (new — pure
`feedback_aggregates(fb_rows, ql_rows)`, no Streamlit/DB, unit-testable),
`src/ui/admin.py` (`_render_feedback_insights`, registered between per-user
stats and security events), `tests/test_step5_feedback.py` (new, 13 tests),
all four `locales/*.json` (7 new `feedback_*`/`admin_feedback_header` keys).

**Toggle-off storage finding (task explicitly asked this be checked):**
rating `"none"` calls `delete_feedback` in `src/logging_db.py` (lines
~151-165), which **deletes** the `recommendation_feedback` row outright —
so "absent = no stance" already held, and `get_downrated_wine_ids`'
latest-rating-wins filter needed no special handling for toggled-off ratings.

**Verified:**
- Full suite green (198 passed, was 185 before this step).
- `tests/test_recommend_for_me.py` (5 tests) passes **unmodified** — exclusion
  defaults to off when `user_id=None`, so legacy call sites keep identical
  behaviour.
- `tests/test_pair_with_food.py` (11 tests) unchanged.
- `git diff sql/` empty — no schema changes (sql/08 already had everything
  needed).
- Grep on `build_recommend_for_me_tool(` call sites: `src/graph.py` (the
  production path) passes `user_id=user_id`; the legacy test file
  intentionally omits it (anonymous semantics).

**Known limitations (recorded per task, not fixed):**
- The exclusion query (`get_downrated_wine_ids`) runs once per
  `recommend_for_me` call with no caching — at current scale that's one
  indexed read (`idx_feedback_user`); revisit only if profiling ever shows
  it matters.
- №4 breakdowns attribute a rating to the model/locale of the turn that
  *produced* the recommendation (joined via `query_id`) — correct by
  construction, but sparse early on; treat small-sample acceptance values
  with care.

**Human-only checklist (not yet done — pass to the human):**
1. Log in → get recommendations → 👎 one wine → ask again → that wine is
   absent. 👎 everything shown → next ask yields the honest "all previously
   rejected" reply, one question, no wine names.
2. Admin tab → "Recommendation feedback": metrics, per-wine table, and
   breakdowns render (or show "no data" if the table is empty).

---

## Step 6 — post-completion hardening (6, 6b, 6c, 6d, 6e, 6f, 6g, 6h)

Eight sub-steps, each a self-contained fix found via the human's own
smoke-testing of the Phase 3 core steps above. **Status: all done and
committed** — see "Cumulative status after steps 6 → 6h + 6e" near the end
of this section for the full commit list and final test count.

**6 (base) — `docs/phase3/step6_hardening/`:** adds tests closing five gaps
inherited from `docs/PHASE2_HANDOFF.md`'s "Known gaps" list, plus two
housekeeping fixes. Zero production-behavior changes were made in step 6
itself; step 6b (below) made one deliberate, human-approved behavior change.

**Part A — `tests/test_hardening.py`** (copied as-is, 7 tests): locale-key
parity across all four `locales/*.json` (identical key sets + matching
`{placeholder}` sets + non-empty `welcome_examples` everywhere — generalizes
PHASE2 gap #5), LangSmith-absent graceful import (gap #4), cost-cap boundary
+ documented fail-open behavior (gap #3). All 7 passed against the real repo
on the first run — **no locale drift found**, nothing needed fixing.

**Part B1 — `tests/test_feedback_anonymous.py`** (gap #1) — see the B1
finding + step 6b resolution below.

**Part B2 — `tests/test_extract_preferences_regression.py`** (gap #2, 7
tests): a 12-message ordinary conversation (all 5 spec'd trap cases — grape
mention, style mention, pairing chat, negation without a preference verb,
third-person statement — plus one RU and one DE ordinary query) produces
zero preference signals, verified at both `detect_preference_signals` and
the `extract_preferences_node` graph-node layer (upsert monkeypatched to
fail-fast). Positive controls ("I love dry reds" / "I can't stand sweet
wines") and idempotency (same statement fed twice → no re-detection on the
second pass) also verified. **No `xfail` needed anywhere** — notably the
third-person trap ("my friend loves Riesling...") already fails to match by
construction, since `_SIGNAL_VERB`'s regex requires a literal first-person
"I" token; the detector was already safe on this trap, not just lucky.

**Part C — housekeeping:**
- `.gitignore`: `.env.*` (which accidentally covered `.env.example`) replaced
  with explicit `.env.local` / `.env.*.local`. Verified: `git check-ignore
  .env.example` now exits 1 (tracked), `git check-ignore .env` still exits 0
  (ignored). `.env.example` contains no secrets (all blank template values).
- `CLAUDE.md`: added `docs/PHASE3_HANDOFF.md` to the intro reading list
  (between `PROJECT_HANDOFF.md` and `SPEC.md`), so future sessions read the
  freshest state first. (Note: `CLAUDE.md` itself is gitignored in this repo
  — this edit is local-only, same as before.)

### The B1 finding — and its resolution (step 6b)

Writing `tests/test_feedback_anonymous.py` against the real
`_toggle_feedback` (extracted from `chat_view.render_feedback_buttons`'s
`_toggle` closure for testability — pure refactor, zero logic change)
surfaced a real discrepancy: **only half** of "anonymous users never write
feedback to the DB" held. `fold_feedback`/`delete_feedback` (the
taste-profile writes) were correctly gated on `user_id`, but `log_feedback`
itself was called unconditionally — an anonymous 👍/👎 still inserted a
`user_id=NULL` row into `recommendation_feedback` via the service-role
client (which bypasses RLS). `src/logging_db.py`'s own docstring had
documented this as intentional, and `src/ui/admin.py::_render_user_stats`
already filtered `user_id.notna()` on that table — so it wasn't an obvious
accident either way. Per the step 6 task's explicit instruction, this was
**not** silently fixed: the one affected assertion was marked
`xfail(strict=True)` and reported for a human decision, rather than
weakened or hidden.

**Human decision (step 6b): variant (b)** — the invariant stands as written
in CLAUDE.md / SPEC Appendix B / PHASE2_HANDOFF. Decisive argument:
`recommendation_feedback`'s `unique(user_id, query_id, wine_id)` constraint
cannot deduplicate NULL-user rows (Postgres `NULL != NULL`), so anonymous
re-taps would insert duplicate rows and silently skew the step-5 №2/№4
admin analytics (per-wine counts, acceptance rate). The one sql/08 comment
describing anonymous inserts as intentional loses to three documents
asserting the opposite; `sql/08` itself was **not** edited (applied files
are never edited per CLAUDE.md) — its nullable `user_id` column simply
becomes unused capacity for anonymous rows.

**Fix (`src/ui/chat_view.py`):**
1. `_toggle_feedback`: the `log_feedback` call is now gated behind
   `if not user_id: return` (same style as the pre-existing
   `fold_feedback`/`delete_feedback` gates) — the DB write path is
   user-gated end to end. Confirmed via `grep log_feedback(` that this is
   the *only* call site in the codebase.
2. `render_feedback_buttons`: when there is no authenticated user, it now
   renders a single `st.caption(t("feedback_login_hint", locale))` instead
   of any buttons at all — mirroring the sidebar taste-profile pattern, and
   avoiding a UI that looks broken (a click with no visible effect). The
   gate in (1) remains as defense-in-depth behind this hidden UI — layers
   don't trust each other.
3. New locale key `feedback_login_hint` added to all four `locales/*.json`
   (enforced going forward by the step-6 locale-parity test).

`tests/test_feedback_anonymous.py`'s `xfail(strict=True)` was removed; the
assertion (now consolidated: zero calls to both `log_feedback` and
`fold_feedback` for anonymous users, in one test) passes for real. A new
UI-layer test confirms `render_feedback_buttons` draws zero `st.button`
calls and shows the hint caption for an anonymous session. **Zero xfails
remain in the suite.**

**Deliberate backlog item:** anonymous feedback for admin analytics
(purchasing-signal aggregates across all visitors, not just logged-in
users) would need `session_id`-based deduplication instead of the current
`user_id`-based unique constraint — not attempted here; revisit only if
there's a concrete product need for anonymous-inclusive analytics.

**Verification (6+6b only):** full suite green, **217 passed, 0 xfailed**
(198 baseline + 7 Part A + 5 B1 + 7 B2). `git diff --stat` for step 6+6b
combined touched only: `.gitignore`, `.env.example` (newly tracked),
`src/ui/chat_view.py`, all four `locales/*.json`, and the three new test files.
Committed as `eaf5177`.

### 6c — normalize Whisper silence hallucinations (`docs/phase3/step6c_silence_fix/`)

**Found in the human's voice smoke test:** on silent audio, Whisper returned
`"."` (not an empty string) — that passed the `if not res["text"]` check and
burned a full LLM turn + rate-limit slot + retrieval call on a punctuation
mark. **Fix:** `src/transcribe.py` now normalizes any transcript with no
letters/digits (`not re.search(r"\w", text)`) to `""`, so the UI shows the
"couldn't hear anything" toast instead. Plausible-word hallucinations (e.g.
`"Thank you."`) remain accepted as-is — indistinguishable from real speech,
a known limitation. New tests in `tests/test_transcribe.py` (+2, now 12 total).
Verified: 219 passed. `git diff --stat`: only `src/transcribe.py` +
`tests/test_transcribe.py`. Committed as `8750ab2`.

### 6d — rotate the audio_input widget key (`docs/phase3/step6d_voice_widget/`)

**Found in the human's voice smoke test:** after every consumed recording,
`st.audio_input` rendered "An error has occurred, please try again" (with
the previous recording's duration) on the next rerun — the widget is built
on file-uploader infrastructure and keeps referencing the stale consumed
upload. Functional behavior was already correct (digest dedup prevents
reprocessing); this was a UI-only annoyance forcing an extra click between
voice turns. **Fix:** `app.py`'s voice-input block now rotates the widget
key (`voice_recorder_{gen}`) via a session-state generation counter, bumped
on every *consumed* recording (success, silence, or transcription error) —
NOT on the rate-limit branch, where the recording wasn't consumed and
should stay available for retry. No test-count change (widget-lifecycle
code, correctly left to the human smoke test per the task). `git diff --stat`:
only `app.py`. Committed as `d1fb9a5`.

### 6e — recommend_for_me freshness + only-these-wines hardening (`docs/phase3/step6e_recommend_freshness/`)

**Found in the human's step-5 smoke test — two linked bugs:** (A) on a
follow-up "recommend me something" turn, the LLM sometimes skipped the
`recommend_for_me` call entirely and re-presented wines from conversation
history (zero tool calls that turn, so the 👎-exclusion code — correct in
itself — never even ran); (B) `recommend_for_me`'s SUCCESS payload, unlike
`pair_with_food`'s, carried no "recommend ONLY these" instruction, so the
LLM could supplement the tool's results with a 3rd wine from RAG context,
bypassing the profile's price constraint (that extra wine correctly got no
feedback buttons, which is how the bug surfaced). **The step-5 exclusion
code itself was never implicated** — it was simply never reached.

**Fix — three layered defenses, none structural (see residual note below):**
1. `src/tools/recommend_for_me.py`: the personalized SUCCESS payload now
   carries an `agent_instruction` ("Present ONLY these N wine(s) ... Do NOT
   add, substitute, or re-present any other wine ... earlier recommendations
   in the chat history are stale"), mirroring `pair_with_food`'s pattern.
   The `no_profile_general` / `all_downrated` / `no_catalog_match` payloads
   are unchanged. The tool's `description` also gained two sentences: call
   it FRESH on every request, even a repeated one — results change with the
   profile or 👍/👎 feedback.
2. `src/agent.py`: the RECOMMENDATION QUERIES system-prompt block gained
   two new numbered rules (call `recommend_for_me` every turn even if
   already called earlier in the conversation; never re-present
   conversation-history wines as fresh recommendations). Every existing
   rule (including the PAIRING QUERIES block and all NEVER/ALWAYS rules)
   verified byte-identical via `git diff`.
3. `src/agent.py::_build_messages` gained an optional `route` parameter;
   when `route == "recommend"`, one extra system message ("Router: this
   turn is a recommendation request. You MUST call recommend_for_me before
   answering...") is appended right before the user's query — a
   deterministic backstop for exactly the turn where the LLM was observed
   skipping the tool. `src/graph.py::agent_node` passes
   `route=state.get("route")` through. No other route's messages change.

New `tests/test_recommend_freshness.py` (9 tests): the success payload gains
"ONLY"/"stale" wording while the other three result branches don't; the tool
description mentions "FRESH" and "ONLY the wines this tool returns"; the
nudge message is present only for `route="recommend"` and absent for
`general`/`compare`/`None`. `tests/test_pair_with_food.py` and
`tests/test_recommend_for_me.py` verified to pass **unmodified**. Verified:
249 passed. `git diff --stat`: `src/tools/recommend_for_me.py`,
`src/agent.py`, `src/graph.py`, `tests/test_recommend_freshness.py` (new).
Committed as `cc98236`. Human re-ran the exact failing scenario post-fix —
see "Smoke-test campaign summary" below for the full 7-step result.

**Known residual (LLM-compliance, not a structural guarantee):** prompt +
description + nudge is strong but the model could still skip the tool
despite all three layers. If a future smoke test catches this again, the
next escalation is structural: pre-invoke the bound `recommend_for_me` in
the graph for the recommend route and inject its result as a tool message —
deliberately not done now, a bigger change to the ReAct loop than this bug
justified.

### 6f — enforce the §5.4 fold guard ("positive preference wins") (`docs/phase3/step6f_fold_guard/`)

**Found in the human's smoke test:** a 👎 on two Assyrtiko wines wrongly
added Assyrtiko to `disliked_grapes` even though it was already in
`preferred_grapes` at fold time — violating SPEC §5.4 ("explicit positive
preference wins over a single 👎"). **Root cause:** `fold_feedback`
(`src/preferences.py`) and its sidebar mirror `_fold_cache`
(`src/ui/chat_view.py`) both used "move" semantics on 👎 — unconditionally
stripping the value out of `preferred_*` and pushing it into `disliked_*`,
with no guard checking whether it was already preferred. The style
dimension in the same incident looked correct only because "Crisp & Zesty"
wasn't preferred to begin with (the illegal removal was a harmless no-op).
**Fix:** a 👎 now only adds to `disliked_*` when the value is NOT already
preferred, and never touches `preferred_*` either way, in both
implementations. `_fold_cache`'s mutation logic was extracted into a
standalone `_fold_profile_dict` so a parity test (`tests/test_fold_guard.py`,
new file, 5 tests) can run both implementations on identical inputs and
assert they agree. Also fixed an existing test in `tests/test_preferences.py`
that had literally codified the "move" bug as correct behavior. Verified:
226 passed. `git diff --stat`: `src/preferences.py`, `src/ui/chat_view.py`,
`tests/test_preferences.py`, `tests/test_fold_guard.py` (new). Committed as
`b1c8793`.

**Data cleanup needed (human, before re-testing):** the smoke-test profile
was polluted by the bug — Assyrtiko ended up in `disliked_grapes`. Manually
move it back to Preferred grapes in the sidebar (and consciously decide on
Crisp & Zesty) before re-running the smoke scenario, otherwise the stray
disliked-grape hard constraint forces `no_catalog_match`. **Superseded by
6h's fix below** — see 6h's data-cleanup note, which reflects the final
state after both fixes landed. **Status: DONE** (human completed the
cleanup — see "Smoke-test campaign summary" below).

### 6g — typography-safe title matching, the 'White Ash' incident (`docs/phase3/step6g_title_match/`)

**Root cause of the original "buttons for 2 of 3 wines" bug:**
`recommend_for_me` returned "Leonidas Nassiakos 'White Ash' Assyrtiko"
(curly quotes, as stored in the catalog); the LLM presented it with straight
apostrophes; `chat_view._title_in_response`'s raw
`clean.lower() in response_text.lower()` substring check failed, so the
wine was filtered out of the feedback-button list as "fetched but not
presented" — zero buttons rendered for a wine the user genuinely saw.
**Fix:** new `_normalize_for_match` helper + `_TYPOGRAPHY` translation table
(curly→straight quotes, long dashes→hyphen, nbsp→space, whitespace collapse,
casefold) applied to both sides of the comparison — deterministic, no fuzzy
matching. Region/vintage stripping and the empty-title-permissive behavior
are unchanged. New `tests/test_title_matching.py` (7 tests) pins the
incident both directions plus regressions for plain titles, absent-wine
rejection, and the unchanged stripping/permissive behavior. Verified: 233
passed. `git diff --stat`: only `src/ui/chat_view.py` +
`tests/test_title_matching.py` (new). Committed as `e1d1724`.

### 6h — make un-fold the exact inverse of fold (`docs/phase3/step6h_unfold_provenance/`)

**Found in the human's smoke test (continuation of 6f):** toggle-off
("none") removed a wine's grape/style/type from BOTH `preferred_*` and
`disliked_*` unconditionally — the original Phase-2 design — but the fold
it was supposed to undo (guarded per §5.4 since 6f) may have added NOTHING,
e.g. a 👎 on a wine whose grape+style were already manually preferred.
Toggling off such a 👎 wiped `preferred_grapes`/`preferred_styles` outright.
**Fix:** each applied fold's delta (exactly what it added/removed) is now
serialized as JSON into `recommendation_feedback.reason` (sql/08, previously
unused — no schema change) on the same row write. Toggle-off reads that
delta back (new `get_feedback_reason` in `src/logging_db.py`) and reverts
EXACTLY it before deleting the row; a rating flip (down→up or up→down)
reverts the outgoing delta first, then applies+records the new one.
Missing/legacy/unparseable reason → revert nothing (safe default — the row
deletion's wine-id exclusion lift is still the primary effect).
`fold_feedback` now returns `(updated_profile_or_None, applied_delta)`
instead of just the profile (no caller used the old return value — safe
signature change). The pure fold/revert math
(`_compute_and_apply_fold` / `_revert_fold_delta`) is unified —
`chat_view._fold_profile_dict` now imports and calls these same functions
instead of maintaining a second copy, closing off the exact class of drift
that caused 6f's bug in the first place. New `tests/test_fold_provenance.py`
(6 tests: the incident, partial-overlap fold + correct revert,
manual-dislike survival through a no-op-fold toggle-off, a down→up flip, a
legacy NULL-reason row, sidebar-cache parity), plus updated
`tests/test_fold_guard.py` and `tests/test_feedback_anonymous.py` for the
new `fold_feedback(..., delta=...)` signature. Verified: **240 passed, 0
xfailed**, `git diff sql/` empty. `git diff --stat`: `src/preferences.py`,
`src/logging_db.py`, `src/ui/chat_view.py`, `tests/test_fold_guard.py`,
`tests/test_feedback_anonymous.py`, `tests/test_fold_provenance.py` (new).
Committed as `49c3be2`.

**Data cleanup needed (human, before re-testing — supersedes 6f's note):**
the smoke-test profile is still polluted from before 6f/6h landed. Re-add
Assyrtiko to Preferred grapes and Crisp & Zesty to Preferred styles;
consciously decide on Ripe & Rounded in Disliked styles (it's a legitimate
fold from the still-active White Ash 👎 — leaving it is correct). After
that, the step-5 smoke scenario should rerun cleanly: toggle Skouras's 👎
off → re-ask → Skouras returns; profile arrays unchanged throughout.
**Status: DONE** — profile restored, Ripe & Rounded consciously kept as a
legitimate fold from the still-active White Ash 👎 (see "Smoke-test
campaign summary" below for the full re-test result).

### Cumulative status after steps 6 → 6h + 6e — all committed

All seven hardening commits (`eaf5177`, `8750ab2`, `d1fb9a5`, `cc98236`,
`b1c8793`, `e1d1724`, `49c3be2`) are on `main` and pushed to `origin/main`.
Final suite: **249 passed, 0 xfailed, 21 deselected** (integration/eval
tests). No SQL changes across any of steps 6–6h/6e. `test_pair_with_food.py`
(11 tests) and `test_recommend_for_me.py` (5 tests) verified unchanged
after every single step in this chain.

Every real-world human smoke test has now passed — see "Smoke-test campaign
summary" below for the full 7-step scenario and the six defects it
originally surfaced (all fixed by steps 6c/6d/6e/6f/6g/6h). See "Outstanding
human-only checklists" at the very end of this document for the final,
all-DONE-except-tag status.

---

## Smoke-test campaign summary

**Headline:** a single 7-step live scenario (real UI, real LLM, real DB —
no mocks) surfaced **six real defects**, none of which were catchable by
mocked unit tests, because every one of them lived on a *seam* rather than
inside a single function's logic: LLM↔tool (did the model actually call the
tool it was told to?), catalog-data↔matcher (does stored typography survive
an LLM's paraphrase?), widget-lifecycle↔rerun (does Streamlit's own state
survive a consumed upload?), and UI↔profile (does a UI action produce
*exactly* the DB mutation it should, no more, no less?). Unit tests validate
logic in isolation; this campaign is what actually caught the bugs — a
reminder that live smoke-testing remains load-bearing even with a green
test suite.

**Scenario (all 7 steps passed after fixes):**

| # | Step | Verifies |
|---|------|----------|
| 1 | Fresh recommend → tool called, buttons per presented wine | 6e |
| 2 | 👎 on fully-preferred wine → no fold | 6f guard |
| 3 | Re-ask → downvoted wine absent, sibling remains | №1 exclusion |
| 4 | 👎 second wine → style-relaxed alternative surfaces | exclusion × Phase-2 relaxation |
| 5 | Buttons on typographic-quoted title; partial fold correct | 6g + 6f |
| 6 | All rated down → honest all_downrated, no wine names | №1 honesty branch |
| 7 | Toggle-off → exclusion lifted, manual profile untouched | 6h |

**Defects found → fixed:**

| Defect | Root phase | Fix |
|---|---|---|
| LLM skipped recommend_for_me on repeat turns; supplemented from history | 3 (step 5) | 6e |
| Whisper hallucinated "." on silence → burned an LLM turn | 3 (step 4) | 6c |
| audio_input stale-upload error between voice turns | 3 (step 4) | 6d |
| 👎-fold overwrote explicit preferred grape (§5.4 violation) | 2 | 6f |
| Typographic quotes broke title matching → missing feedback buttons | 1 (catalog data era) | 6g |
| Toggle-off wiped manual preferences (un-fold ≠ inverse of fold) | 2 | 6h |

"Root phase" refers to when the defect was actually introduced (Phase 1
catalog data, Phase 2 preferences/feedback design, or Phase 3 step build),
not when it was found — all six were only discoverable once Phase 3 wired
voice input, fresh feedback exclusion, and delta-provenance together and a
human actually drove the UI.

---

## Known accepted gaps (do not fix without explicit ask)

1. **Guard-blocked turns are not persisted to the durable log** — canned
   off-topic/injection replies vanish on refresh. Accepted per SPEC step 9 task.

2. ~~Anonymous invocations still checkpoint transient per-turn state under
   `anon:*` threads; rows are orphaned and harmless (anonymous threads are
   ephemeral by design — new uuid every session, so they're never read back).
   Future housekeeping: periodic `delete_thread` sweep of `anon:*` threads.~~
   **RESOLVED (Phase 4, step 3).** New `src/checkpointer.py::sweep_anon_threads()`
   — manual, admin-triggered sweep (button in the Developer settings panel,
   `src/ui/admin.py`), not a cron (Streamlit Cloud has none). No-ops on
   `MemorySaver`; on `PostgresSaver` reads distinct `anon:*` thread_ids from
   the library's own `checkpoints` table and deletes each via the official
   `delete_thread` API, with the `anon:` prefix re-checked in Python as a
   second independent guard so a `user:*` thread can never be swept even if
   the SQL filter were ever loosened. Orphaned rows still accumulate between
   manual sweeps — an on-startup opportunistic sweep remains a possible
   future option (not implemented; see Backlog).

3. ~~Login does not survive a real browser refresh (F5).~~ Confirmed during
   Step 1 smoke testing: after F5, `st.session_state.auth` (set in
   `src/ui/auth_view.py::_set_authed_session`) is cleared — the user is logged
   out, even though the durable chat log itself is intact and reloads
   correctly once they log back in. This was **pre-existing behavior, not a
   Step 9 regression** — auth state only ever lived in `st.session_state`,
   which has no cookie/localStorage/query-param-backed persistence layer.
   **RESOLVED (Phase 4, step 4).** See "Phase 4, step 4" section below for
   the full design, security note, and rotation caveat.

---

## Backlog (deliberately deferred)

Consolidated list — every deferred item mentioned anywhere else in this
document is cross-referenced here, plus a few new engineering-hygiene items.
None of these are blocking; revisit only on concrete product/ops need.

1. ~~Login persistence across F5~~ **RESOLVED (Phase 4, step 4b — step 4's
   first attempt failed its own smoke test and was redesigned).** See
   "Known accepted gaps" #3 above and the "Phase 4, step 4" / "Phase 4,
   step 4b" sections below.
2. ~~"Forget me" doesn't delete `recommendation_feedback` rows.~~ **DONE.**
   `delete_preferences` (+ `delete_thread` since step 1) cleared the taste
   profile and durable chat log, but a user's historical 👍/👎 rows survived
   under their `user_id` — found during smoke-test prep. **Fix:** new
   `delete_all_feedback(user_id)` in `src/logging_db.py` (deletes by
   `user_id` only, no `wine_id` filter — distinct from the per-wine
   `delete_feedback` used by the toggle-off UI flow; swallows exceptions,
   same best-effort principle), wired in as one line next to
   `delete_preferences`/`delete_thread` in the sidebar's "Forget everything
   about me" handler (`src/ui/sidebar.py`). New `tests/test_logging_db.py`
   (2 tests: correct `user_id`-only delete call, exceptions swallowed).
   Verified: 251 passed (was 249, +2). `git diff --stat`:
   `src/logging_db.py`, `src/ui/sidebar.py`, `tests/test_logging_db.py`
   (new).
3. ~~Multilingual parity for the 30 food nouns~~ **RESOLVED (Phase 4, step
   2).** See "Phase 4, step 2" section above for the full vocabulary added
   per language and the new Finnish stem mechanism.
4. ~~`stt_usage` cost accounting~~ **RESOLVED (Phase 4, step 3).** See Step
   4's "Known gaps" above for the fix summary — reminder: `sql/10_stt_usage.sql`
   must be applied via the Supabase SQL Editor before deploy.
5. ~~`anon:*` checkpoint thread housekeeping~~ **RESOLVED (Phase 4, step 3),
   manual-only.** See "Known accepted gaps" #2 above. Remaining refinement,
   not implemented: an on-startup opportunistic sweep so orphans don't
   accumulate between manual admin clicks.
6. **Feedback features №3/№5/№6** (step 5, human-decided out of scope):
   cold-start prior (№3), collaborative filtering (№5), profile-drift
   detection (№6).
7. **Anonymous ratings for admin analytics** (step 6b) — would need
   `session_id`-based deduplication instead of the current `user_id`-based
   unique constraint, since anonymous rows can't dedupe on NULL. Not
   attempted; revisit only for a concrete anonymous-analytics need.
8. **Relaxed-match "top-up" idea** — when `_preferred_subset` relaxes the
   style constraint and returns fewer than `limit` matches, there's no
   mechanism to "top up" the remaining slots with additional
   identity-constrained-but-style-relaxed candidates; currently the shorter
   list is simply returned as-is. Worth a look if under-filled recommend
   results become a reported issue.
9. **"1 picks" pluralization** — `tool_recommend_result`'s locale string
   ("{count} picks for you: {titles}") doesn't special-case `count == 1`
   ("1 picks" instead of "1 pick"). Minor i18n copy polish across all four
   locales.
10. **CI: run `pytest` on push/PR** — no GitHub Actions workflow currently
    runs the test suite automatically; it's only ever been run locally by
    Claude/the human. Would catch regressions before merge.
11. **Supabase client deprecation warnings** — test runs emit
    `DeprecationWarning`s from the `supabase`/`postgrest` client about the
    `timeout`/`verify` constructor parameters (seen repeatedly in this
    session's `pytest` output). Cosmetic today; worth clearing before the
    next `supabase-py` major version removes the fallback.
12. ~~`pytest` runs burn the LangSmith trace quota.~~ **DONE.**
    `src/config.py`'s `LANGSMITH_TRACING`/`LANGSMITH_ENABLED` are read
    straight from the real environment (`load_dotenv()`), so any test that
    exercised a traced graph path (`run_via_graph`/`agent_node` and friends)
    created a real LangSmith trace whenever the local `.env` had tracing
    enabled — observed directly in this session as `LangSmithRateLimitError:
    Monthly unique traces usage limit exceeded` during full-suite runs. Not
    a bug: graceful degradation working exactly as designed (the
    rate-limited traces failed silently in the background; every test still
    passed) — but wasteful, since tracing exists for the live app, not CI.
    **Fixed:** `tests/conftest.py` now sets
    `os.environ["LANGSMITH_TRACING"] = "false"` at the top of the file,
    before any project import — python-dotenv doesn't override an
    already-set var, so this wins over the local `.env`'s `true`. Verified:
    confirmed the real `.env` had `LANGSMITH_TRACING=true` before the fix;
    after the fix, full suite (249 passed) runs with zero LangSmith network
    calls or rate-limit noise. `git diff --stat`: only `tests/conftest.py`
    (9 lines added).
13. ~~`test_us004_compare_wines_uses_tool` picks `explain_wine_concept` over
    `compare_wines` for a grape-variety comparison.~~ **RESOLVED (Phase 4,
    step 1).** The old test's own assertion was wrong, not the app: per the
    SPEC's tool boundaries, `compare_wines` is for "2-3 named wines" while
    variety-vs-variety comparisons legitimately belong to
    `explain_wine_concept` ("grape, region, term, or style") — the test
    encoded pre-v2.0 behavior (before `explain_wine_concept` existed) and
    was gating on LLM non-determinism over a genuinely ambiguous case.
    **Fix:** split into two tests in `tests/eval/test_agent_eval.py`:
    `test_compare_named_wines_uses_compare_tool` (two REAL catalog wine
    titles, fetched live via `get_active_wines_df()` — the two cheapest
    active reds, so catalog drift can't rot the test — must strictly call
    `compare_wines`) and `test_compare_varieties_uses_either_tool` (the old
    "Compare Malbec and Cabernet Sauvignon" query, now asserting either
    `compare_wines` or `explain_wine_concept` was called — tool choice is
    no longer gated, only groundedness is, via a shared
    `_assert_no_hallucinated_compare_wines` helper reusing the same
    catalog-membership pattern as `test_pair_with_food_results_are_all_catalog_wines`).
    Old test deleted; dataset/fixtures otherwise untouched. **Verified for
    real** (Windows, no ragas needed — these two don't compute Ragas
    metrics): `pytest tests/eval/test_agent_eval.py -k compare -m
    integration` → both new tests passed on the first run. Default `pytest
    -q` count unchanged (251 passed; eval tests went 21→22 deselected,
    +1 net from the split). `git diff --stat`: only
    `tests/eval/test_agent_eval.py` + this handoff file.
14. **Checkpointer pickles `src.rag.RetrievedWine` into state** (observed in
    logs during Phase 4 step 4b's manual testing, unrelated to the cookie
    work itself) — a `msgpack` deprecation warning surfaces when
    `PostgresSaver` serializes `AgentState`; a future `langgraph` release
    will block non-plain-dict payloads outright. Consider serializing
    `rag_context` to plain dicts before it enters `AgentState`, mirroring
    what `src/checkpointer.py`'s `serialize_wine`/`serialize_chat_entry`
    already do for the chat log's `sources`. Not attempted here — logged for
    a future step, no functional impact observed yet.
15. **Dev/admin panel state survives logout on a shared machine** (found
    during Phase 4 step 4c while enumerating what `reset_to_anonymous()`
    should clear — see that section's "Not in scope" note). `admin_unlocked`,
    `dev_model_override`, `dev_temperature`, `dev_tools_enabled` are untouched
    by logout/forget-me. Worst case: an admin overrides `dev_temperature`
    away from 0.2, logs out without re-locking the panel, and the NEXT
    anonymous user's chat runs at that overridden temperature — `app.py`
    applies `dev_temperature` regardless of `admin_unlocked` — a latent,
    adjacent violation of "temperature stays 0.2 for all end-user paths" on
    a shared device. Not fixed in step 4c (out of that task's explicit
    scope); revisit if shared-machine/kiosk-style deployment becomes a real
    use case.
16. **Forget-me doesn't call `sign_out()`** (found while re-examining Phase 4
    step 4c's design). The forget-me handler clears local session state and
    the persistence cookie, but never revokes the Supabase session itself —
    the access/refresh token pair stays valid server-side until it expires
    on its own. In practice this is low-risk (the client-side cookie and
    session are both already gone, so nothing in this app can present that
    token again), but it means "Forget everything about me" doesn't fully
    match what "Log out" does. Forget-me should also call `sign_out()` to
    revoke the server-side session, not just drop the client's access to
    it. Not fixed here; revisit alongside any future session-management
    hardening.

---

## Offline eval verification (`tests/eval/`, run once post-6h/6e)

Run once against the final Phase-3 + hardening code (via the WSL venv,
which has `ragas` installed — Windows can't build it without MS C++ Build
Tools) to confirm the exclusion/fold-guard/un-fold changes (6e–6h, all
ranking-adjacent) didn't regress grounding or personalization. Real
OpenRouter + Supabase calls — not part of the default `pytest` run.

- **20 of 21 passed.** The one failure (`test_us004_compare_wines_uses_tool`)
  is recorded as backlog item #13 above — judged unrelated to the hardening
  changes, and since **resolved** (Phase 4, step 1: the test itself was
  wrong; split into two correctly-scoped tests, both passing for real).
- **Ragas faithfulness: 0.367** (gate is ≥0.20). The test's own code comment
  records the original baseline as "~0.27" — this run is *higher*, not
  lower, so grounding did not regress.
- **Ragas context_precision: 0.000** — not gated by design (the lightweight
  8-example dataset uses `reference=""` for every sample, so precision
  isn't meaningful without a ground truth; documented in the test itself).
- **`test_pair_with_food_results_are_all_catalog_wines` passed** — the most
  direct end-to-end grounding check (real graph + real LLM, not a mocked
  tool): zero hallucinated `wine_id`s across the whole dataset.
- The dataset's personalised-recommendation example ("Recommend something
  for me tonight") completed with `status == "ok"`, exercising the 6e
  freshness fix end-to-end for real, though Ragas only reports an aggregate
  score, not a per-example one.

---

## Sacred invariants — confirmed intact across all 5 steps + hardening (6–6h, 6e)

1. Triple anti-hallucination defense — `app.py::_agent_history` /
   `_history_source_ok` untouched (verified via `git diff` after every step);
   `pair_with_food.py` (layer 1, canonical) untouched throughout Phase 3.
2. `sql/01`–`09` untouched — no Phase 3 step added or modified SQL. Checkpointer
   tables are library-owned (`scripts/setup_checkpointer.py`, not `sql/`);
   feedback exclusion/insights reused `sql/08` as-is.
3. `DATABASE_URL` / `TRANSCRIBE_MODEL` via `os.getenv`, never `config._require`
   — same graceful-degradation philosophy as `LANGSMITH_API_KEY`.
4. Retry→fallback loop in `agent_node` byte-identical throughout.
5. Preferences/feedback still only shape search/ranking — `recommend_for_me`'s
   new exclusion logic narrows the candidate set inside the catalog; it never
   invents or substitutes a non-catalog wine.

---

## Outstanding human-only checklists (across all steps — canonical list)

This is the single up-to-date list; per-step sections above may restate
individual items but this is the one to actually work through. **Every item
is now DONE except the optional tag.**

1. **Step 1 (checkpointer):** run `scripts/setup_checkpointer.py` once
   against `DATABASE_URL` — **DONE**, confirmed working (see Step 1 section).
2. **Step 4 / 6c / 6d (voice):** real mic + real API smoke test across all 4
   locales, plus a voice prompt-injection test to confirm guard parity with
   typed input. — **DONE.** All 4 locales transcribed and answered
   correctly; an EN phrase spoken under the FI locale was transcribed
   correctly and answered in FI (confirms the locale governs reply
   language, as designed — not a bug). A spoken prompt-injection phrase
   triggered the guard's canned reply and wrote a `security_events` row,
   confirming full pipeline parity between voice and typed input. Silence
   now shows the "couldn't hear anything" toast (6c); consecutive voice
   turns need no manual widget reset (6d).
3. **Step 5 (feedback):** manual 👎-then-re-ask smoke test; visual check of
   the admin "Recommendation feedback" tab. — **DONE.** The full 7-step live
   scenario passed after the 6e/6f/6g/6h fixes — see "Smoke-test campaign
   summary" below for the complete step-by-step result.
4. **Steps 6f/6h data cleanup:** re-add Assyrtiko to Preferred grapes and
   Crisp & Zesty to Preferred styles in the sidebar; consciously decide on
   Ripe & Rounded in Disliked styles. — **DONE.** Profile restored; Ripe &
   Rounded consciously kept as a legitimate fold from the still-active White
   Ash 👎.
5. **Step 6b (anonymous feedback UI):** anonymous session → recommendations
   → no 👍/👎 buttons, login hint shown; logged-in → buttons work as before,
   toggle still toggles. — **DONE.** No buttons rendered for anonymous
   sessions, login hint shown and verified in both EN and FI; confirmed no
   `user_id=NULL` rows are written to `recommendation_feedback` anymore.
6. **Step 6e (recommend freshness — the exact failing scenario):** profile
   with only Assyrtiko preferred; "Recommend me something for tonight" →
   Tools used shows `recommend_for_me` called, buttons appear for every
   presented wine; 👎 all presented wines; ask again → Tools used present
   again (fresh call), result excludes all 👎 wines. — **DONE**, folded into
   the 7-step campaign below (steps 1, 3, 6).
7. **Secret-leak grep:** `git log -p --all | grep -i "lsv2_\|sbp_\|sk-\|eyJ"`
   — **DONE**, human ran it and Claude independently re-verified: 5 matches,
   all safe (README's own truncated placeholder secrets + two false
   positives on markdown anchor text). No real secrets in history.
8. **Optional:** git tag marking the hardened Phase-3 state, on `cc98236`
   (the final hardening commit) or later — **not yet created**; fill in the
   tag name/date here once the human creates it: `___________`.
