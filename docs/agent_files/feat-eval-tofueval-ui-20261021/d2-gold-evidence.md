# D2 task 7 — GoldPanel evidence

Implemented independently on `feat/eval-tofueval-ui`, without merging or modifying the
auxiliary D2 branch. D1 task-list frontmatter is now `done` as explicitly authorized;
only D2 task 7's status cell was changed.

## Behavior

- `GoldPanel` selects a renderer from an own-property registry keyed by `goldKind`.
- `TofuEvalGold` guards summary and sentence labels against the actual C2 enum,
  `consistent | inconsistent`, and validates all required fields before rendering.
  It preserves supplied sentence order/indices, text, native error types and
  explanations. It does not fill missing indices or recompute summary labels.
- Unknown kinds, including prototype property names, and malformed known shapes use
  `GenericGold`: collapsed details with pretty JSON.
- Known gold starts expanded and can collapse. Isolated gold CSS limits the entire
  details panel, including its summary, to 30vh with scrolling.
- Components import React and local gold modules only; no imports from `app/`.

`GoldPanelProps.goldKind` accepts `string | null`, matching the API's nullable kind.
Wiring GoldPanel into ItemDetail remains task 8; this commit adds the standalone panel.

## TDD and verification

Commands ran from `frontend/`, with fictional annotation data and no fetches:

```text
npx vitest run src/eval/gold/GoldPanel.test.tsx
 Test Files  1 failed (1)
      Tests  15 failed (15)
# Initial empty implementation: native rendering, fallback and collapse absent.

npx vitest run src/eval/gold/GoldPanel.test.tsx -t 'starts known'
 Test Files  1 failed (1)
      Tests  1 failed | 14 skipped (15)
# Additional refinement: cap must include the entire details panel, not just content.

npx vitest run src/eval/gold/GoldPanel.test.tsx
 Test Files  1 passed (1)
      Tests  15 passed (15)
   Duration  1.56s

npm test && npm run typecheck && npm run build
 Test Files  34 passed (34)
      Tests  475 passed (475)
   Duration  13.76s
> tsc --noEmit -p .
> tsc --noEmit -p . && vite build
vite v8.3.4 building client environment for production...
✓ 163 modules transformed.
✓ built in 326ms
(exit 0)

git diff --check
(no output; exit 0)
```

An intermediate CSS assertion failed because Vitest omits stylesheet imports, including
CSS `?raw` imports. The test now loads the actual CSS file into jsdom and checks the
computed viewport-relative cap and overflow. Jsdom resolves 30vh to pixels; the test
compares that result with 30% of viewport height. No production workaround was needed.

Coverage includes known gold, raw indices with gaps, native type strings, escaped
explanations, unknown/prototype kinds, malformed summary/sentence labels, missing or
invalid fields, collapse and the panel height limit. No protected review components,
audit contracts, backend files, or D2 task 5 files changed. Owner checks against real
TofuEval annotations remain deferred; no downloads, live provider calls or browsers ran.
