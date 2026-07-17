# TASK: Phase 3, step 6b — resolve the B1 finding (anonymous feedback gate)

> For Claude Code. Follow-up to step 6. Human decision: **variant (b)** —
> the CLAUDE.md / SPEC-Appendix-B invariant stands as written ("anonymous
> users never write preferences/feedback to the DB"); the code is brought in
> line with it. The sql/08 comment describing anonymous rows loses; do not
> edit sql/08 (applied files are never edited) — the schema's nullable
> user_id simply remains unused capacity.

## Why (b), for the record
Three documents (CLAUDE.md working rule, SPEC Appendix B, PHASE2_HANDOFF)
assert the invariant vs one sql/08 comment against it. Decisively: the
table's `unique(user_id, query_id, wine_id)` cannot deduplicate NULL-user
rows (Postgres NULL ≠ NULL), so anonymous re-taps would insert duplicates
and silently skew the step-5 №2/№4 analytics. Variant (b) removes that bug
class outright. Revisiting anonymous analytics later is a deliberate backlog
item requiring session_id-based dedup.

## Edits

### 1. `src/ui/chat_view.py` — two changes
a) In `_toggle_feedback(...)`: gate the `log_feedback` call on `user_id`
   (same style as the existing `fold_feedback` gate). With this, the DB
   write path is user-gated end to end.
b) In `render_feedback_buttons(...)` (or equivalent): when there is no
   authenticated user, render NO buttons — show a single
   `st.caption(t("feedback_login_hint", locale))` instead, mirroring the
   sidebar taste-profile pattern. The gate in (a) stays as defense-in-depth
   behind the hidden UI (project philosophy: layers don't trust each other).

### 2. `tests/test_feedback_anonymous.py`
Remove the `@pytest.mark.xfail(strict=True)` from the mandated assertion —
after edit 1a it must PASS (strict xfail would otherwise fail the suite).
Keep every assertion; add one for the UI layer if cheaply testable
(anonymous → `render_feedback_buttons` draws no `st.button`), otherwise
leave UI verification to the human smoke test.

### 3. Locale files — 1 new key in ALL FOUR
en: `"feedback_login_hint": "Log in to rate recommendations."`
de: `"feedback_login_hint": "Melde dich an, um Empfehlungen zu bewerten."`
ru: `"feedback_login_hint": "Войдите, чтобы оценивать рекомендации."`
fi: `"feedback_login_hint": "Kirjaudu sisään arvioidaksesi suosituksia."`
(The step-6 locale-parity test will enforce this across files automatically.)

### 4. `docs/PHASE3_HANDOFF.md` — document the resolution
Short entry under step 6: the B1 finding, the human decision (variant b,
with the NULL-dedup rationale), and the backlog item ("anonymous ratings for
admin analytics — requires session_id-based dedup — deliberately deferred").

## Verification
1. `pytest` — full suite green, ZERO xfails now (the strict xfail is gone,
   the assertion passes). Locale-parity test green with the new key.
2. Manual reasoning check in the report: confirm no other call site writes
   `recommendation_feedback` for anonymous users (grep `log_feedback(`).
3. `git diff --stat` — only chat_view.py, the test file, 4 locale files,
   PHASE3_HANDOFF.md.
4. STOP for review. After human approval: commit everything from step 6 +
   6b together (suggested message:
   `test(phase3): hardening — inherited gap tests, anon-feedback gate, env hygiene`).

## Human-only checklist (after commit)
1. Smoke: anonymous session → recommendations → no 👍/👎 buttons, hint shown;
   logged-in → buttons work as before, toggle still toggles.
2. The four standing items from step 6 (secret grep, voice smoke, step-5
   smoke, optional tag) remain open — this step adds only #1 above.
