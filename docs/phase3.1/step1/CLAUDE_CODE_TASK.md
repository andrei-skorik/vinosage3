# TASK: Phase 4, step 1 of 4 — split the compare-tool eval test

> For Claude Code. Read `CLAUDE.md` and `docs/PHASE3_HANDOFF.md` (backlog
> item #13) first. Smallest task of the batch; one step per run, stop for
> review, as always.

## Problem
`tests/eval/test_agent_eval.py::test_us004_compare_wines_uses_tool` asserts
that "Compare Malbec and Cabernet Sauvignon" calls `compare_wines`. Per the
SPEC's own tool boundaries that assertion is wrong: `compare_wines` is for
"2–3 **named wines**"; a variety-vs-variety comparison legitimately belongs
to `explain_wine_concept` ("grape, region, term, or style"). The test
encodes pre-v2.0 behavior (before explain_wine_concept existed) and fails on
LLM non-determinism over a genuinely ambiguous case — noise, not signal.

## Fix — split into two tests
1. **`test_compare_named_wines_uses_compare_tool`** — query names two REAL
   catalog wines and must STRICTLY call `compare_wines`. Fetch the two
   titles dynamically from `get_active_wines_df()` at test time (e.g. the
   two cheapest active reds) instead of hardcoding, so catalog drift can't
   rot the test. Query template: `f"Compare {title_a} and {title_b}"`.
   Assert: status ok; `compare_wines` in tool calls; every wine named in
   the answer exists in the catalog (reuse the file's existing
   hallucination-check helper if present).
2. **`test_compare_varieties_uses_either_tool`** — the old query ("Compare
   Malbec and Cabernet Sauvignon"). Assert: status ok; at least one of
   {`compare_wines`, `explain_wine_concept`} was called; zero invented
   wines in the answer (same helper). The tool CHOICE is no longer gated —
   both are spec-legitimate.

Delete the old test; keep dataset/fixtures otherwise untouched. Keep both
tests in the eval marker group (deselected from the default run, real API).

## Verification
1. Default `pytest -q` — count unchanged (eval tests stay deselected).
2. If the environment can execute eval tests (real keys are in .env; ragas
   itself is NOT needed for these two — they don't compute Ragas metrics):
   run exactly these two once
   (`pytest tests/eval/test_agent_eval.py -k "compare" -m eval` or the
   repo's equivalent selector) and report pass/fail. If the environment
   cannot (e.g. Windows/ragas import at module scope), say so explicitly —
   the human will run them in the WSL venv.
3. `docs/PHASE3_HANDOFF.md`: mark backlog item #13 resolved with one line
   describing the split.
4. `git diff --stat` — only the eval test file + handoff. STOP for review.

## Human checklist
If Claude Code couldn't run them: in the WSL venv,
`pytest tests/eval/test_agent_eval.py -k compare` once; expect 2 passed.
