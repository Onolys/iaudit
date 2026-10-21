# Eval UI reference

**Audience:** users.

The **Eval** tab runs local dataset evaluations against the audit backend. It shows
run setup, progress, run results, saved items and comparisons. API endpoints and server configuration are in
[eval-api.md](eval-api.md); the audit upload flow is in [review-ui.md](review-ui.md).

## Audit and Eval

The app opens in **Audit**. Use the **Audit** and **Eval** buttons above the current
screen to switch modes. Switching unmounts the current screen: leaving Audit discards
the loaded audit and selection, and cancels an in-flight audit request. Returning to
Audit shows the upload prompt.

Leaving Eval stops its browser requests and polling. A server-side run continues;
returning to Eval or reloading scans the server's runs and attaches to a running run.
Only the last selected dataset is remembered in local storage, when storage is
available. Split, N and screen selection reset on remount.

## Run setup

| Control | Behavior |
|---|---|
| Dataset | Lists datasets known to the eval server. Selecting a dataset loads its metadata and default split. |
| Split | Declared splits plus `all`, which selects their union. Selecting `test` shows the dataset's held-out-split note when supplied. |
| N | Blank selects the whole split. Otherwise enter an integer of at least 1. On leaving the field, N above a known split size is clamped with `N clamped to {size}`. For `all`, the clamp uses the sum only when every split size is known. |
| Estimate | Updates after 400 ms without input changes. Known cost appears as `~$X.XX for {n_items} items (rough)`. Unknown cost shows the server's note, or `Cost unknown — run a pilot (e.g. N=5) first`. |
| Max cost (USD) | Optional. Blank sends no cap. A supplied value must be greater than zero. An untouched field is prefilled with 1.5 × a known positive estimate, rounded up to cents; unknown cost leaves it blank. Editing the field, including clearing it, preserves that choice across estimates. |

Invalid N or max cost disables **Run** and shows an inline explanation. Unknown cost
alone does not disable Run. Estimates are rough, and in-flight requests can finish
beyond a cost cap. If a cap is set and the backend does not report cost, the run fails
closed; the panel shows the `failed` state and the server's actual failure message.

## Start, download, watch and abort

**Run** starts the selected evaluation and attaches to its progress. The panel shows
completed/total items, failures and a progress bar. Cost appears only when the server
reports it. Run polling is sequential, with the next poll about one second after the
previous response.

If required data is absent, **Download data** replaces Run. The same happens when a
start attempt returns `data_missing`. Downloading shows `downloading…` and polls until
ready or failed. Failure shows the returned error and **Retry download**. Completion
refreshes dataset metadata and restores Run when the server reports the data present.

**Abort** lets server-side in-flight work finish. The button reads **Aborting…** and
is disabled while the abort request is pending. Terminal states hide Abort and refresh
the runs list. The cost-cap state is displayed as `aborted: cost cap`.

The server permits one active run. If a start returns `run_active`, the panel shows
`Run {id} is already active` and **Attach to active run**. Mounting Eval also attaches
automatically to a running run, so a reload can recover progress without starting it
again.

## Runs list

The table shows selection, creation date, dataset, split, N (selected item count),
schema version, state, cost and failures. Unavailable cost or schema version is `—`.
It refreshes on mount, after start/abort/resume/terminal progress, and with **Refresh**.
The active row uses the Run panel's progress; it has no separate progress poller.

| State | Resume |
|---|---|
| `running` | Unavailable |
| `finished`, no failed items | Unavailable |
| `finished`, at least one failed item | Available |
| `aborted`, `aborted_cost`, `interrupted`, `failed` | Available |

**Resume** retries failed or missing results while preserving successful ones. Resume
buttons are disabled while a run is active or starting/attaching, or another resume
request is pending. A pending resume also blocks Run. A successful resume attaches
to the existing Run panel's polling.

Click a row or its date button to open that run. Checkboxes and Resume do not open
the row. Select at most two runs from the same dataset; incompatible and additional
unchecked boxes are disabled. **Compare selected (2)** opens the selected comparison.
Run rows open their results. Comparison selection opens the two-run comparison.

## Environment and proxy

Set frontend values in `frontend/.env.local`, starting from
[.env.example](../../frontend/.env.example).

| Variable | Default | Effect |
|---|---|---|
| `VITE_EVAL_API_BASE` | `/eval-api` | Browser API base, fixed at frontend build time. |
| `IAUDIT_EVAL_PORT` | `8100` | Local target port read by Vite configuration; also used by the Python server entrypoint. |
| `VITE_AUDIT_URL` | See `.env.example` | Audit endpoint; independent of Eval. |
| `VITE_MOCK` | Off unless exactly `true` | Bundled Audit fixtures only; Eval has no mock mode. |

Both Vite dev and preview proxy `/eval-api` to
`http://127.0.0.1:${IAUDIT_EVAL_PORT}`, preserving the original Host. The proxy strips
`/eval-api`: a browser request to `/eval-api/health` reaches the server's `/health`.
The eval API serves its routes at the root. The frontend defaults to port 5173 in the
[development script](../../scripts/README.md), which fixes backend/eval/frontend ports
to 8000/8100/5173 and supplies matching environment settings.

This is a local development/preview setup. Hosted deployment configuration is outside
this UI version. Requests omit cookies. Client timeouts are 10 seconds for reads and
30 seconds for POST requests.

## Empty and error states

| Situation | Display or action |
|---|---|
| Eval health request fails | `Eval server not reachable` banner with **Retry**; Audit remains usable. |
| No registered datasets | `No datasets in eval/datasets/` |
| Dataset metadata/list load fails | Error and **Retry run form** |
| Missing data | **Download data** |
| Download fails | Error and **Retry download** |
| No runs | `No runs yet. Start one above.` |
| Runs-list request fails | Error; **Refresh** retries the list. |
| Three consecutive progress/download poll failures | `Lost contact with eval server — retrying`; polling continues and recovery clears the banner. Last run progress stays visible. |
| `schema_mismatch` or `backend_unreachable` | API message and supplied detail/version information displayed as server text. |
| Run terminates unsuccessfully | State chip and run-level error message when supplied; Resume follows the state rules above. |

## Run detail and Re-score

Run detail shows dataset, split, selected N, creation date and state, then failures,
metrics, items and run information. **Back to runs** returns to the list.

**Re-score** recomputes saved results without calling the audit backend or a model.
It is disabled while the run is running or scoring is pending/running. `Scoring...`
replaces the metrics table until scoring finishes; the screen polls and then fetches
fresh metrics. A failed score shows `Scoring failed. Re-score to retry.` Missing metrics
after scoring finishes show `Metrics missing. Re-score.` A 404 `not_found` on the
metrics route means missing metrics, rather than a failed run-detail request.

Metrics are grouped by level, then slice, preserving server order. Primary values
count failures wrong; secondary values exclude failures. Each policy has its own
value, n and confidence interval. Hover for cluster counts. An unavailable interval
shows `-` with a `few_clusters` or `undefined` hint. The failure sentence uses item
counts; policy-none rates appear separately with their level and slice, so sentence
or summary rates cannot be mistaken for counts of failed items.

Paper reference rows follow their matching metric, retain the paper's evaluator
label and show `paper-reported, different model & date`. They are grey, value-only
rows with dashes elsewhere; they are never ranked or colored by performance.
**Reference caveats** is a collapsed note.

Run information shows commit/dirty state, models per tier, prompt hashes (eight
characters with the full hash on hover), mapping version, seed, supplied tags,
reported cost or `unknown`, and tokens only when supplied. Mixed fingerprints and
saved warnings remain visible. Test runs add `Test runs are for reporting, not tuning.`

## Items and saved review

The item table filters **all**, **mismatch** or **failed** with one high-limit request.
Columns show the item's label or ID, Gold, Ours, Match and failed status. Empty filters
show `No items match this filter.` Prior rows stay visible and dimmed while a new
filter loads. Click a row or its item button to open it.

A saved item shows a back action, gold annotations and the same assessment/evidence
review as Audit. This is read-only replay: selecting claims changes the view, and
neither starts an audit nor edits saved data. There is no upload control. **Back to
run** returns to the originating run; **Back to comparison** returns to the same
comparison pair.

Failed items show saved failure kind, HTTP status, error code, message and up to
50 issues when supplied, followed by `No response was saved. Resume the run to retry.`
They do not open the review panes. An unmapped item states its scoring limitation;
it can still replay a valid saved response. If none exists, it says
`No saved audit response is available.`

Saved requests and responses pass the same validators as Audit. The current audit
contract pin is **1.1.0**: stale 1.0.0 responses show the unsupported-version error.
The planned A1 pin change to 1.2.0 will also reject saved 1.1.0 items. This is an
accepted limitation; there is no replay compatibility layer. Run lists, saved
metrics and comparisons remain available independently of item replay validation.

### Gold kinds

`tofueval_summary_sentences` shows the supplied summary label and, for each sentence,
its index, text, consistent/inconsistent label, native error-type strings and
explanation. Gold is collapsible and scrolls within a 30vh cap. Unknown kinds or
malformed TofuEval gold fall back to collapsed, pretty-printed JSON. Gold text is
not highlighted inside the assessment pane.

## Compare results

Select two runs of one dataset in the runs list. The comparison identifies A and B
and prominently reports `n shared = k`. Its plain table shows metric, level, slice,
policy, A, B, signed delta **B − A**, and delta CI only when its status is `ok`.
Values have no better/worse coloring. Zero shared items show `No shared items`.

Disagreements show the item and each differing pair's level, unit, gold, A and B.
**open in A** and **open in B** inspect that item's saved audit in the chosen run.
Cross-dataset errors appear inline, including the server's current HTTP 422 response
and HTTP 409 responses. Network failures use the server banner with **Retry**.

## Owner manual checks

Offline tests cover fake-fetch lifecycle behavior, timers, unmount cancellation and
the proxy against a stub. The following live checks remain for the owner:

- Launch the stack with `scripts/dev.sh` and provider credentials; start a small pilot
  (for example N=5), close and reopen the tab in a real browser, and confirm attachment
  to the same running run.
- Verify `/eval-api/health` through the Vite dev server against the real eval server.
- After downloading the real dataset and completing a paid pilot, open one real
  TofuEval item and compare its gold with the source CSV; inspect run detail and compare.
- Open the largest saved item and check its load time in a real browser.
- After A1, verify that older 1.1.0 items show the unsupported-version screen while
  run lists, metrics and comparisons still work.

Full-stack launches, live provider calls and real dataset downloads are owner checks;
they are not performed by the automated frontend test suite.
