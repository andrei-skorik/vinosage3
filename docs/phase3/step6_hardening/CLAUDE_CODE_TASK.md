# TASK: Phase 3, step 6 (post-completion hardening) — inherited Phase-2 gaps + housekeeping

> For Claude Code. Read `CLAUDE.md`, `docs/PHASE2_HANDOFF.md` ("Known gaps vs
> SPEC acceptance criteria") and `docs/PHASE3_HANDOFF.md` first. This step adds
> TESTS and two one-line housekeeping fixes — zero production-behavior changes
> are expected. If closing a gap seems to require changing production code,
> STOP and report instead of changing it.

## Scope
Five inherited Phase-2 gaps (#1–#5 from PHASE2_HANDOFF "Known gaps") plus two
housekeeping items found during Phase 3. Grouped as:
- **Part A** — ready-made test file, copy as-is (gaps #3, #4, #5).
- **Part B** — two test files YOU write against the real code (gaps #1, #2),
  specs below with mandatory assertions.
- **Part C** — housekeeping: `.env.example` tracking + a CLAUDE.md doc line.

## Part A — `tests/test_hardening.py` (copy as-is from `docs/phase3/step6_hardening/tests/`)
7 tests:
- **Locale parity (gap #5, generalized):** all four `locales/*.json` share an
  identical key set (failure message names the drifted locale and exact keys);
  every `{placeholder}` set matches en.json per key; `welcome_examples`
  non-empty everywhere. This subsumes the original "check fi.json has all
  explain_*/recommend_* keys" and closes the whole bug class.
- **LangSmith absence (gap #4):** subprocess import of `src.config` with all
  `LANGSMITH_*` env vars set to empty strings → exit 0, `LANGSMITH_ENABLED is
  False`. (Empty strings, not delenv: python-dotenv doesn't override existing
  vars, so `.env` values can't leak back.)
- **Cost cap (gap #3, unit level):** blocks at exactly `DAILY_COST_CAP_MICROS`,
  allows at cap−1, and PINS the documented fail-open behavior (DB error →
  `get_daily_cost_micros() == 0` → allowed). Fail-open is a conscious
  availability-over-accounting trade-off; the test makes reversing it a
  deliberate act.

If the parity test fails on the REAL locale files, that's a genuine drift
find: fix the locale files (add the missing keys with proper translations),
not the test. Report any keys you had to add.

## Part B — two spec'd tests (write against the real code)

### B1. `tests/test_feedback_anonymous.py` — gap #1
**Invariant (SPEC Appendix B):** anonymous users never write feedback to the
DB. The guard lives in the feedback toggle handler in `src/ui/chat_view.py`
(`_toggle` or equivalent — locate it).

Mandatory assertions:
1. With no authenticated user in session state, triggering the toggle logic
   results in ZERO calls to `src.logging_db.log_feedback` AND ZERO calls to
   `src.preferences.fold_feedback` (monkeypatch both to `pytest.fail(...)`).
2. Positive control: with an authenticated user present, the same path DOES
   call both (monkeypatch to recorders; assert called with the expected
   rating and wine).

Implementation latitude: if `_toggle` is inseparable from Streamlit widget
state, you may do a MINIMAL extraction (e.g. a pure `_should_persist(auth) ->
bool` or passing the auth dict as a parameter) — but keep behavior identical,
keep the function in chat_view.py, and describe the refactor in your report.
Do not restructure the feedback UI.

### B2. `tests/test_extract_preferences_regression.py` — gap #2
**Invariant (SPEC §5.3):** `extract_preferences` writes only on explicit,
confident signals — never on ordinary wine chat.

Build a realistic multi-turn conversation of at least 10 ordinary messages
that MUST NOT trigger a write, including these trap cases:
- single-word grape/style mentions: "recommend a Malbec", "any good sweet
  wines?" (mention ≠ preference);
- pairing chat: "what pairs with sweet desserts?";
- negations without preference verbs: "not too expensive";
- a question about someone else: "my friend loves Riesling, what should SHE
  try?" (must not write to THIS user's profile — if the current detector
  can't distinguish this, mark the case `xfail` with a comment rather than
  weakening the assertion);
- at least one RU and one DE ordinary query.

Run each through `detect_preference_signals(text, existing_profile)` (and, if
cheaply possible, through the `extract_preferences` node with a monkeypatched
`upsert_preferences` recorder) and assert `changed is False` / zero upserts
for every one. Positive controls: "I love dry reds" and "I can't stand sweet
wines" → `changed is True` with the expected fields; assert idempotency
(feeding the same statement twice against the updated profile → second pass
`changed is False`, no duplicate values).

## Part C — housekeeping
1. **`.env.example` is untracked** — the `.gitignore` pattern `.env.*`
   accidentally covers it, so the documented env-var template (now including
   `DATABASE_URL`, `TRANSCRIBE_MODEL`) exists only on the human's machine.
   Fix by narrowing `.gitignore` (e.g. replace `.env.*` with explicit `.env`,
   `.env.local`, `.env.*.local`) — verify with `git check-ignore -v
   .env.example` before/after, then `git add .env.example`. Confirm `.env`
   itself REMAINS ignored (this is critical — check twice).
2. **`CLAUDE.md`:** in the intro reading list, add `docs/PHASE3_HANDOFF.md`
   after `docs/PROJECT_HANDOFF.md`, so future sessions read the freshest
   state. One line; touch nothing else in the file.

## Verification (run all before stopping for review)
1. `pytest` — full suite green. Expected: 198 + 7 (Part A) + Part B's count.
   `test_pair_with_food.py` unchanged, as always.
2. `git diff src/ app.py` — EMPTY except (possibly) the minimal B1 extraction
   in `src/ui/chat_view.py` and any locale-file key additions from Part A.
   Zero behavior changes anywhere else.
3. `git check-ignore .env.example` exits non-zero (no longer ignored);
   `git check-ignore .env` exits 0 (still ignored).
4. Report: Part A locale findings (keys added, if any), B1 refactor details
   (if any), B2 trap-case results (any xfails and why), final test count.
5. STOP for human review.

## Human-only checklist (unchanged from Phase 3 — restated so it isn't lost)
1. Secret-leak grep before any push: `git log -p --all | grep -i
   "lsv2_\|sbp_\|sk-\|eyJ"` — especially relevant now that `.env` contains
   `DATABASE_URL` with the DB password.
2. Voice smoke test (all 4 locales + spoken prompt-injection → guard fires).
3. Step-5 smoke test (👎 → re-ask → wine absent; all-👎 → honest reply) and
   the admin "Recommendation feedback" visual check.
4. Optional: git tag on the Phase-3 commit (e.g. `v2.1-phase3`).
