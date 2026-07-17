# TASK: Phase 3, step 3 of 5 — heal _FOOD_KWS drift + add the sync guard (variant A)

> For Claude Code. Read `CLAUDE.md` first. No reference snapshots this time —
> the repo has moved past my snapshots (steps 1–2 landed), so this task gives
> surgical edits only. The test file in `docs/phase3/step3_food_kws/tests/` is
> the deliverable that defines "done".

## Background — a real bug, not just hygiene
The triple anti-hallucination defense keeps three deliberately independent
copies of the food-keyword data. **They have drifted.** Layer 1
(`pair_with_food._FOOD_NOUNS`, 64 items) gained 30 nouns over time; layers 2
(`agent._FOOD_KWS`) and 3 (`app._HIST_FOOD_KWS`) and the routing set
(`agent._FOOD_QUERY_KWS`) were never updated. For queries about those 30
foods ("what wine with prawns?"), routing does not classify the turn as a
food query and the layer-2/3 evidence filters never engage — defense-in-depth
degraded from three layers to one.

**Approved remedy = variant A:** keep three independent copies (the sacred
invariant stands — do NOT merge, share, or import sets across layers), bring
layers 2/3 and routing back in sync with layer 1, and add a sync test so the
next drift turns the build red with an explicit diff.

## Edits

### 1. `src/agent.py` — hoist `_FOOD_KWS` to module level
`_FOOD_KWS` is currently a local variable inside `_build_messages` — the sync
test cannot import it. Move the set literal (with its "dessert omitted" /
"cake omitted" comments) to module scope, next to `_FOOD_QUERY_KWS`. The
nested `_in_kws` helper keeps referencing it; zero logic change. It remains
agent.py's OWN copy — do not import it from anywhere.

### 2. Extend three sets with the 30 missing nouns
Add exactly these words (already present in `pair_with_food._FOOD_NOUNS`,
which is canonical and MUST NOT be edited — it's on the do-not-touch list):

```
"pudding", "puddings", "mousse", "fondue", "brownie", "brownies",
"tart", "tarts", "bread", "brioche", "flatbread", "noodle", "noodles",
"dumpling", "dumplings", "prawn", "prawns", "crab", "squid", "octopus",
"scallop", "scallops", "quail", "pheasant", "burger", "soup", "stew",
"chilli", "chili", "tapas",
```

Apply to:
- `src/agent.py :: _FOOD_KWS` (after hoisting),
- `app.py :: _HIST_FOOD_KWS`,
- `src/agent.py :: _FOOD_QUERY_KWS` (English section only — so routing
  recognizes every evidence-capable noun).

Do NOT add `"cake"` or `"dessert"` anywhere. After the edits, the three
evidence sets must be exactly equal to `_FOOD_NOUNS` (the test asserts this
set-wise, so formatting/ordering is free).

**Safety argument (why this cannot weaken grounding):** adding keywords to
layers 2/3 makes the evidence filter engage on MORE queries — strictly
stricter. Adding them to routing forces MORE queries through the mandatory
pair_with_food path. Layer 1's tool behaviour is untouched.

### 3. Copy `tests/test_food_kws_sync.py` as-is
From `docs/phase3/step3_food_kws/tests/`. 8 tests: set equality across the
three layers (with drift diff in the failure message), "cake" absent from all
evidence sets but present in routing, routing ⊇ evidence, the three
trigger-regex patterns+flags identical, and three behavioral regressions
pinning that layers 2/3 and routing now engage for "prawns"/"stew".

If Python 3.14 lazy annotations bite (they shouldn't — no function-local
`Annotated` here), apply the module-level-import remedy without changing
assertions.

## Verification (run all before stopping for review)
1. **Red first:** run `pytest tests/test_food_kws_sync.py` BEFORE applying
   edit 2 — `test_three_evidence_sets_are_identical`,
   `test_routing_recognizes_every_evidence_noun` and the behavioral tests
   must FAIL (proves the test detects the real drift). Then apply edits and
   confirm all 8 pass.
2. Full suite green — especially `test_pair_with_food.py` unchanged (layer 1
   untouched, so any failure there means you edited the wrong file).
3. `git diff src/tools/pair_with_food.py` must be EMPTY.
4. `git diff src/agent.py app.py` — confirm only: the hoist, the set
   extensions, nothing else. `_build_messages` logic, `_is_food_query` logic,
   `_history_source_ok`, and all three trigger regexes must be untouched.
5. Summarize the diff and STOP for human review. Do not proceed to step 4.

## Known gap to record in the Phase-3 handoff (out of scope now)
The 30 new nouns are English-only. `_FOOD_QUERY_KWS`'s DE/FI sections and
`_RU_FOOD_STEMS` do not cover them (e.g. RU "креветк" exists but "суп" does —
check; DE "Garnele" exists but "Suppe" does not). Multilingual parity for the
expanded noun list is a separate, human-approved vocabulary task — do not
attempt it in this step.

## Human-only checklist
None — no secrets, no SQL. Review the diff; the 30-word list above is the
one product decision embedded in this step (which foods count as evidence).
