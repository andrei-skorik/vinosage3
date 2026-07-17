# TASK: Phase 3, step 5 of 5 — feedback features №1 / №2 / №4

> For Claude Code. Read `CLAUDE.md` first. Reference files in
> `docs/phase3/step5_feedback/`. Three isolated features, three isolated
> diffs — they share tests and this task, nothing else.

## The three features (human-approved scope)
- **№1 — exclusion list:** `recommend_for_me` must never re-recommend a wine
  the user currently has a 👎 on, even when it matches the profile on every
  other dimension. Includes an honesty branch: when the user's own rejections
  are the ONLY reason for an empty result, say that (`all_downrated`) instead
  of the misleading "nothing matches".
- **№2 — per-wine feedback table (admin):** 👍/👎 counts + down-share per
  wine — a purchasing signal for the shop.
- **№4 — acceptance rate (admin):** share of 👍 among all ratings, overall +
  trend by date + breakdown by model and locale — a continuous online quality
  metric complementing the offline Ragas evals.

Explicitly OUT of scope (backlog, human decision): global cold-start prior
(№3), collaborative filtering (№5), profile-drift detection (№6).

## Sacred-invariant note
№1 only NARROWS the candidate set inside the catalog — preferences/feedback
still shape search and ranking only, never invent wines. №2/№4 are read-only
aggregates. No anti-hallucination layer, tool matching logic, or SQL file is
touched; no new tables (sql/08 already holds everything needed).

## Files to apply

### 1. `src/tools/recommend_for_me.py` — MODIFIED, reference copy provided
Diff against the repo (changes are localized):
- new `_excluded_wine_ids(user_id)` helper (lazy import of
  `src.preferences.get_downrated_wine_ids`, swallows all failures → empty
  set; `user_id=None` short-circuits without any DB call);
- `_build(...)` gains `user_id: str | None = None`; splits the hard mask into
  `base_hard` (dislikes + price) vs `hard_mask = base_hard & ~excluded`, and
  adds the `all_downrated` honesty branch (checked BEFORE the unstocked
  check, and only when lifting the exclusion alone yields matches);
- `_diverse_picks(...)` gains `excluded` and drops those wines in the
  empty-profile path too;
- `build_recommend_for_me_tool(profile, user_id=None)` — user_id captured in
  the closure alongside the profile (the LLM still passes no identity).
Everything else (style relaxation, ranking, rationale wording) is unchanged.

### 2. `src/preferences.py` — ADD one function (surgical; I don't have this file)
```python
def get_downrated_wine_ids(user_id: str) -> set[str]:
    """Wine_ids the user currently has an active 👎 on (latest rating wins).

    Latest-wins: the same wine may carry ratings from different turns
    (unique key is user+query+wine); the most recent one is the user's
    current stance. Service-role read, mirroring fold_feedback's client;
    returns an empty set on ANY failure — exclusion is best-effort and must
    never block recommendations (project convention).
    """
    try:
        db = <same service-role client acquisition fold_feedback uses in this file>
        rows = (
            db.table("recommendation_feedback")
            .select("wine_id, rating, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        latest: dict[str, str] = {}
        for r in rows:  # newest-first: first occurrence per wine wins
            wid = r.get("wine_id")
            if wid and wid not in latest:
                latest[wid] = r.get("rating")
        return {wid for wid, rating in latest.items() if rating == "down"}
    except Exception:
        return set()
```
Replace the `<...>` placeholder with the file's actual service-client helper
(the same one `fold_feedback` / `upsert_preferences` use). One subtlety to
verify while you're in the file: check how the toggle-off ("none") is stored —
if it DELETES the row, the code above is already correct (absent = no stance);
if it stores a literal `'none'`-like state some other way, adapt the
latest-wins filter so a toggled-off 👎 does NOT exclude. State what you found
in the report.

### 3. `src/graph.py` — thread user_id into the tool builder (2 lines)
`_tools_for_route(route, profile, disabled_tools=None)` →
`_tools_for_route(route, profile, disabled_tools=None, user_id=None)`; the
recommend branch becomes
`tools = TOOLS + [build_recommend_for_me_tool(profile, user_id=user_id)]`;
`agent_node` passes `user_id=state.get("user_id")` in its `_tools_for_route`
call. Nothing else in the graph changes.

### 4. `src/feedback_insights.py` — NEW, copy as-is
Pure aggregation (`feedback_aggregates(fb_rows, ql_rows)`), no Streamlit/DB —
unit-testable math for №2/№4.

### 5. `src/ui/admin.py` — add `_render_feedback_insights` + register
Paste the function from `admin_render_reference.py` after
`_render_user_stats`, then register in `render_admin()` between the user-stats
and security-events sections:
```python
    st.subheader(t("admin_feedback_header", locale))
    _render_feedback_insights(locale)
    st.divider()
```

### 6. `tests/test_step5_feedback.py` — NEW, copy as-is
13 tests: exclusion in the personalized path, exclusion in diverse picks,
the `all_downrated` honesty branch (and that it never masks a genuine
`no_catalog_match`), anonymous short-circuit (preferences must NOT be
queried), failure-swallowing, closure binding; plus aggregates: totals,
acceptance, per-wine table + down-share + sorting, title→id fallback,
model/locale breakdowns, date trend, empty inputs.
Note: the test builds its own mock df; if the repo's `conftest.mock_df`
fixture pattern is preferred, you may adapt the fixture wiring but keep every
assertion intact.

### 7. Locale files — 7 new keys in ALL FOUR files
`locales/en.json`:
```json
"admin_feedback_header": "Recommendation feedback",
"feedback_ratings_total": "Ratings",
"feedback_acceptance_label": "Acceptance rate",
"feedback_trend_label": "Acceptance over time",
"feedback_by_wine_label": "Per-wine feedback",
"feedback_breakdown_model": "By model",
"feedback_breakdown_locale": "By locale"
```
`locales/de.json`:
```json
"admin_feedback_header": "Empfehlungs-Feedback",
"feedback_ratings_total": "Bewertungen",
"feedback_acceptance_label": "Akzeptanzrate",
"feedback_trend_label": "Akzeptanz im Zeitverlauf",
"feedback_by_wine_label": "Feedback pro Wein",
"feedback_breakdown_model": "Nach Modell",
"feedback_breakdown_locale": "Nach Sprache"
```
`locales/ru.json`:
```json
"admin_feedback_header": "Фидбек по рекомендациям",
"feedback_ratings_total": "Оценок",
"feedback_acceptance_label": "Доля 👍",
"feedback_trend_label": "Динамика доли 👍",
"feedback_by_wine_label": "Фидбек по винам",
"feedback_breakdown_model": "По моделям",
"feedback_breakdown_locale": "По языкам"
```
`locales/fi.json`:
```json
"admin_feedback_header": "Suositusten palaute",
"feedback_ratings_total": "Arviot",
"feedback_acceptance_label": "Hyväksyntäaste",
"feedback_trend_label": "Hyväksyntä ajan mittaan",
"feedback_by_wine_label": "Palaute viineittäin",
"feedback_breakdown_model": "Malleittain",
"feedback_breakdown_locale": "Kielittäin"
```
(Admin UI is admin-only, but the project convention — every user-facing
string in all four locales — applies to the admin tab too; follow it.)

## Verification (run all before stopping for review)
1. `pytest` — full suite green, incl. the 13 new tests, the unchanged
   `test_pair_with_food.py`, AND the existing `tests/test_recommend_for_me.py`
   (its 5 tests must pass unmodified — the exclusion defaults to off when
   `user_id` is None, so legacy call sites keep identical behaviour).
2. `git diff sql/` — empty (no schema changes in this step).
3. Grep: `build_recommend_for_me_tool` call sites — all pass `user_id` (graph)
   or intentionally don't (tests with anonymous semantics).
4. Report what you found about the toggle-off storage (task §2).
5. Summarize the diff and STOP for review. This is the LAST Phase-3 step —
   after review, update `docs/PHASE3_HANDOFF.md` with the completed-state
   summary (a separate, human-triggered task).

## Human-only checklist
1. Manual smoke test: log in → get recommendations → 👎 one wine → ask again
   → that wine is absent; 👎 everything shown → next ask yields the honest
   "all previously rejected" reply with one question and no wine names.
2. Admin tab → "Recommendation feedback": metrics, per-wine table, breakdowns
   render (or "no data" if the table is empty).

## Known limitations to record in the handoff
- The exclusion query runs once per `recommend_for_me` call (no caching);
  at current scale that's one indexed read (idx_feedback_user) — revisit only
  if profiling ever shows it.
- №4 breakdowns attribute a rating to the model/locale of the turn that
  PRODUCED the recommendation (join via query_id) — correct by construction,
  but sparse early on; treat small-sample acceptance values with care.
