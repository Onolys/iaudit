---
status: done
summary: PASS — initial full offline sweep retained below; post-review fix 98ad587 passes 1395 backend tests and lint; all reviewers PASS.
date: 2026-10-28
---
# SP03 Task8 — Offline acceptance

Verified implementation through `0923e05` on `feat/eaudit-v0` in the linked worktree. No implementation gaps found; this task adds only this evidence record. No live calls, recordings, TofuEval runs or pushes.

## Fresh verification

Each full suite ran once. Every command below exited zero.

| Working directory | Exact command | Observed result |
|---|---|---|
| `eaudit/` | `uv run pytest -q` | **1357 passed**, 1 warning, 20.06s. Includes `tests/` and `eval/tests/`. |
| `eaudit/` | `uv run ruff check src tests eval` | All checks passed. |
| `eval/` | `uv run pytest -q` | **847 passed**, 53.46s. |
| `eval/` | `uv run ruff check src tests datasets/eaudit/tofueval datasets/eaudit/synthetic` | All checks passed. |
| `frontend/` | `npm test -- --run` | **663 passed**, 50 test files, 24.59s. |
| `frontend/` | `npm run typecheck` | TypeScript exited zero. |
| `frontend/` | `npm run build` | TypeScript and Vite passed; 187 modules transformed. |
| `eaudit/` | `uv run python -m eval.run --mode oracle --gate poc` | **9/9 PASS**, faithful and v1–v8. |

Backend warning: existing `StarletteDeprecationWarning` about `httpx` in FastAPI's test client. Oracle reports the existing unavailable ADHD multi-composition and CDR inputs; neither is an SP03 gate.

## Acceptance mapping

| PRD acceptance item | Evidence and outcome |
|---|---|
| Mission: 17 numbered checks, definitions/examples, four groups; narrowed 6/8/13; agreement with enum/schema/group map | **PASS.** Direct assertion sweep below plus `eaudit/tests/test_concern_groups.py`. Reviewed mission's belief/causality distinction and clinical-scoring boundary against requirements 1/2/5. |
| Four flags: types, verdicts and evidence roles; suppression gates | **PASS.** `test_check_taxonomy_v2.py`: supporting/not-addresses and contradicting observations for every new flag, P1 floors, hedged/attributed opinion and reported causal link suppression, calculation input/number grounding, nonempty known meaning-shift keys and failed inference with qualifying premises. |
| Dedup, revisability, fixed neutral templates | **PASS.** `test_check_dedup_taxonomy_v2.py` pins all requested dominance pairs, enum ordering and revisions for three new types while excluding calculation. `test_check_templates.py` checks rendered templates, banned words, digits, source-text overlap and narrowed wording. |
| Failed-inference gold and atomizer checked | **PASS.** Full suite includes strict gold loading, generator equality, expected ADHD outputs, oracle and failed-inference regressions. [Task5 inventory](gold-check-2026-10-28.md) established no affected gold rows; no regeneration needed. Atomizer explicitly preserves attributed beliefs and the believer in `reported_by`; eight scripted few-shot boundary examples pass in `test_check_taxonomy_prompt_examples.py`. |
| Fictional synthetic cases and backend boundary pairs; zero-spend and leakage checks | **PASS.** `eval/tests/test_synthetic_dataset.py` requires two flagged items and one faithful near-miss per new type, validates all **20** items and runs every item through the offline engine. `test_check_boundary_pairs.py` includes **14** new flagged/faithful variants across seven boundaries. Backend `test_prompt_leakage.py` passed all ten checks, including nonempty corpus, seeded-copy detection and root eval-data scanning; synthetic few-shot overlap/speaker checks passed. |
| Mapping exists in enum, disjoint crosswalk, NMS/RE scored, version 0.0.1 | **PASS.** `eval/tests/datasets/tofueval/test_mapping.py` verifies all mapped values, disjoint rows, exact crosswalk, five unmapped types, MediaSum-only attribution and version/digest. TofuEval pair/metric tests verify NMS and RE produce scored concern pairs rather than recall-only results. |
| Removed prompt labelling rules and mapping history | **PASS.** Direct assertion sweep below; prompt gives new meaning-shift/inference semantics and narrowed definitions. SP04 owns the corresponding concept-document edits. |
| Backend/eval lint and tests; frontend typecheck/tests | **PASS.** Fresh full commands above; frontend production build also passed. |
| TofuEval before/after report | **DEFERRED by owner**, explicitly outside this initiative and not a merge gate. |

## Reproducible consistency sweep

Exact command run from `eaudit/`:

```bash
uv run python - <<'PY'
import json, re
from pathlib import Path
from eaudit.models import ConcernType
from eaudit.models.concern_groups import GROUP_OF
r = Path.cwd().parent
m = (r/'docs/mission.md').read_text()
rows = [s for s in m.splitlines() if re.match(r'\| \*\*\d+\.', s)]
assert len(rows) == 17 and all(len(s.split('|')) == 5 and all(p.strip() for p in s.split('|')[1:-1]) for s in rows)
numbered, groups = {}, {}
for s in m.splitlines():
    if s.startswith('| **') and '`' in s:
        g = re.search(r'\*\*(.*?)\*\*', s)[1].lower().replace(' ', '_')
        for n, t in re.findall(r'(\d+)\. [^;]*?\(`([^`]+)`\)', s): numbered[int(n)], groups[t] = t, g
assert [numbered[n] for n in range(1,18)] == list(ConcernType)
a = json.loads((r/'docs/contracts/audit-response.schema.json').read_text())['$defs']['Concern']
assert a['properties']['type']['enum'] == list(ConcernType)
assert groups == {str(k):str(v) for k,v in GROUP_OF.items()} == {t:c['then']['properties']['group']['const'] for c in a['allOf'] for t in c['if']['properties']['type']['enum']}
for n in ('audit-request','audit-response','error-response'): assert json.loads((r/f'docs/contracts/{n}.schema.json').read_text())['properties']['schema_version']['const'] == '0.0.1'
assert 'hedge' in rows[5].lower() and 'qualification or condition' in rows[7] and 'Totals or arithmetic' in rows[12]
assert all(s in m for s in ('check 14','check 15','Numerical score calculations: scoring rules'))
p = (r/'eaudit/src/eaudit/prompts/check_system.md').read_text()
assert not any(s in p for s in ('Changed action','Merged facts','two true facts joined','replaces narrower with wider','secondhand'))
assert 'mapping_history' not in (r/'eval/datasets/eaudit/tofueval/mapping.py').read_text()
print('PASS: 17 checks/definitions/examples; numbering, enum/schema/groups agree; versions 0.0.1; narrowed definitions/boundaries; obsolete rules/history absent')
PY
```

Output: `PASS: 17 checks/definitions/examples; numbering, enum/schema/groups agree; versions 0.0.1; narrowed definitions/boundaries; obsolete rules/history absent`.

## Limits and owner steps

- Scripted verifier tests prove deterministic decisions given observations; they do not measure live-model precision or prompt effectiveness.
- Leakage checks cover available committed scored material and fictional synthetic text. No downloaded TofuEval corpus is present, so no claim is made about a full-corpus scan or live TofuEval performance.
- `eaudit/eval/recorded/` contains only its README. Actual pipeline replay has missing fixtures; the passing replay/freshness unit tests use test fixtures. Owner re-recording remains required after prompt changes.
- Mission wording was approved before implementation. Owner live TofuEval comparison and latency/p95 measurement remain deferred, with no offline acceptance gate.
- Independent review and push are orchestrator follow-ups. `TASKS.md` was neither read, edited nor staged by this task agent.

## Post-review addendum — 2026-10-28

The full sweep above records the initial implementation through `0923e05`, committed as Task 8 evidence in `6a8fdb9`. Its 1357 backend, 847 eval and 663 frontend counts are historical results for that implementation.

Independent bugs and architecture reviewers identified one issue: blanket failed-inference relabelling also classified missing premises or an absent inference-step judgment as `unsupported_inference`. Commit `98ad587` restricts that concern to an explicitly rejected step with entailing premises; missing/not-addressed/below-floor premises and absent step judgments retain `unsupported_claim`. Successful shared groups and evidence roles remain preserved.

The regression set produced 24 failures before the fix; afterward 169 targeted tests passed. Final verification at `98ad587`: **1395 backend tests passed** and backend Ruff passed. The earlier eval/frontend results remain recorded above; those suites were not unnecessarily repeated because the review fix changed only backend inference synthesis, associated models and backend tests, with no eval/frontend dependency changes. No live calls were made.

Final independent review: **bugs PASS, architecture PASS, security PASS**, including incremental security review of the fix. See [final review](review-2026-10-28-0545.md). Missing owner recordings, live TofuEval runs and latency/p95 measurements remain deferred as documented above. SP04 concept-document updates remain outside SP03 scope.
