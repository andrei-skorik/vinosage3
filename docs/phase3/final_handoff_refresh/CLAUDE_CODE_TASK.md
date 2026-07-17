# TASK: Phase 3 — final handoff refresh (run AFTER step 6e is done)

> For Claude Code. Documentation-only task; zero code changes. Precondition:
> step 6e (docs/phase3/step6e_recommend_freshness/) is implemented, tested,
> and committed — if it is not, STOP and say so.

## Edits to `docs/PHASE3_HANDOFF.md`

### 1. Add 6e everywhere it's missing
- "Current state": add 6e to the hardening-steps enumeration (it currently
  jumps 6d → 6f) and its commit hash to the commit list; update the final
  test count.
- Add a "### 6e — recommend_for_me freshness + only-these-wines hardening"
  section between 6d and 6f, in the same format as the others: the two
  linked bugs (LLM skipped the tool on repeat recommendation turns; success
  payload lacked a "recommend ONLY these" instruction so the LLM
  supplemented tool results from history/RAG), the three-layer fix
  (agent_instruction + prompt block + per-turn route nudge), tests, commit,
  and the recorded residual (prompt-level compliance, not structural; the
  structural escalation — pre-invoking the tool in the graph — is the
  documented next step if it ever recurs).

### 2. Mark the outstanding checklist as DONE with results
Rewrite "Outstanding human-only checklists" — every item except the tag is
now completed by the human (this happened after the handoff was written):
- Voice smoke (step 4/6c/6d): DONE — all 4 locales OK; EN speech under FI
  locale transcribed correctly with FI reply (locale governs reply language,
  as designed); spoken prompt-injection → guard canned reply + security_events
  row (pipeline parity confirmed); silence → "couldn't hear" toast after 6c;
  consecutive voice turns need no widget reset after 6d.
- Step-5 feedback smoke: DONE — full 7-step scenario passed post-fixes (see
  the new summary table below).
- 6f/6h data cleanup: DONE (profile restored; Ripe & Rounded consciously
  kept as a legitimate fold from the active White Ash 👎).
- 6b anonymous UI: DONE — no buttons for anonymous sessions, login hint
  shown (verified in EN and FI), no NULL-user rows written.
- Tag: fill in once created (see below).

### 3. Add a "Smoke-test campaign summary" section (before "Known accepted gaps")
The campaign's headline: a 7-step live scenario surfaced SIX real defects,
none catchable by mocked unit tests (all lived on seams: LLM↔tool,
catalog-data↔matcher, widget-lifecycle↔rerun, UI↔profile). Include both
tables:

Scenario (all steps passed after fixes):
| # | Step | Verifies |
|---|------|----------|
| 1 | Fresh recommend → tool called, buttons per presented wine | 6e |
| 2 | 👎 on fully-preferred wine → no fold | 6f guard |
| 3 | Re-ask → downvoted wine absent, sibling remains | №1 exclusion |
| 4 | 👎 second wine → style-relaxed alternative surfaces | exclusion × Phase-2 relaxation |
| 5 | Buttons on typographic-quoted title; partial fold correct | 6g + 6f |
| 6 | All rated down → honest all_downrated, no wine names | №1 honesty branch |
| 7 | Toggle-off → exclusion lifted, manual profile untouched | 6h |

Defects found → fixed:
| Defect | Root phase | Fix |
|---|---|---|
| LLM skipped recommend_for_me on repeat turns; supplemented from history | 3 (step 5) | 6e |
| Whisper hallucinated "." on silence → burned an LLM turn | 3 (step 4) | 6c |
| audio_input stale-upload error between voice turns | 3 (step 4) | 6d |
| 👎-fold overwrote explicit preferred grape (§5.4 violation) | 2 | 6f |
| Typographic quotes broke title matching → missing feedback buttons | 1 (catalog data era) | 6g |
| Toggle-off wiped manual preferences (un-fold ≠ inverse of fold) | 2 | 6h |

### 4. Backlog section
Ensure one consolidated "Backlog (deliberately deferred)" list exists,
containing: login persistence across F5; "Forget me" also deleting
recommendation_feedback rows; multilingual parity for the 30 food nouns
(DE/FI + remaining RU); stt_usage cost accounting (new sql/10); anon:*
thread housekeeping; feedback features №3/№5/№6; anonymous ratings with
session_id dedup; relaxed-match "top-up" idea; "1 picks" pluralization; CI
(GitHub Actions pytest on push); supabase client deprecation warnings.

## Verification
1. `pytest` — unchanged count (docs-only).
2. `git diff --stat` — only docs/PHASE3_HANDOFF.md.
3. STOP; the human then commits, pushes, and tags.
