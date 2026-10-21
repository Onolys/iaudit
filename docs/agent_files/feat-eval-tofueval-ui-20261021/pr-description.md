Adds TofuEval evaluation with pinned local downloads, schema-valid audit requests, frozen sentence projection, metrics, paper references and integrity reporting. Original Five and Model-Extra results remain separate; balanced accuracy is undefined when either class is absent.

Completes the Eval UI: dataset/run setup, estimates and optional cost cap, download/progress/abort/resume, run results and Re-score, failure-aware metrics and provenance, saved-item review with native gold or JSON fallback, and two-run comparison with item drill-down. Saved replay reuses the audit validators and unchanged review panes without an audit/model call. Scoring and Re-score refresh item rows while preserving the selected filter.

Validation:

- Final integrated frontend: **553 tests across 45 files passed**; typecheck and production build passed.
- Eval: **754 tests passed**; required Ruff checks passed.
- Backend: **1,094 tests passed**; required Ruff check passed. One existing Starlette/httpx deprecation warning.
- Project C and D independent reviews: all three personas PASS; the item-refresh finding is resolved with three regression tests.
- Protected five review files remain unchanged; complete PR-range whitespace and documentation-link checks pass.
- Broader eval lint retains three pre-existing E501 findings in the synthetic adapter; required lint scopes are clean.

[Final Project D review](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/feat-eval-tofueval-ui-20261021/review-D-2026-10-21-final.md), [implementation and verification](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/feat-eval-tofueval-ui-20261021/code-final-project-d-2026-10-21.md), [Project C review](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/feat-eval-tofueval-ui-20261021/review-C-2026-10-21-final.md).

All D1/D2 implementation tasks are complete offline. This PR remains draft: real dataset downloads, provider-backed pilots/live smoke and real-browser checks are deferred to the owner. Saved 1.0.0 item replay is rejected by the current 1.1.0 contract pin; A1's future 1.2.0 pin will also reject saved 1.1.0 items without a compatibility layer.
