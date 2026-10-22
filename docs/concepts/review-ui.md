# Review UI

How to read the review screen. Exact settings and error text are in [reference](../reference/review-ui.md).

**Audience:** users and contributors.

## The two panes

**Left: the assessment.** Each section is a card. Text covered by a claim is underlined by verdict (colour, line style and icon, so colour is never the only cue). Click a claim to select it. Verdict counts at the top and in each card's `⋯` menu jump through claims of one verdict; the right pane then shows "n of N" with previous/next.

**Right: the selected claim.**

1. Verdict and the auditor's explanation.
2. Suggestion, if any (marked "not applied").
3. Potential concerns. Click one to emphasise the excerpts it cites.
4. Excerpts: the transcript turns that support, contradict or qualify the claim, with the exact words highlighted. "Show 3 more turns above/below" reveals surrounding context.

## What things do not mean

- **Insufficient evidence is not "wrong".** The supplied interview does not establish the claim. That differs from contradicted.
- **Concerns are for a person to review.** They are not accusations.
- **Suggestions are never applied.** The app has no write-back.
- **Score and label are display only.** They are never audited.
- **No concern does not mean correct.** It means none was found.
- **Out of scope** claims (for example a diagnosis) are not checked. The reason is shown.
- **Audit notes are paraphrases**, never quotes. Transcript text shown comes only from the uploaded file.

## When the audit is incomplete

- **Partial audit:** a banner lists warnings. Unprocessed sections are labelled "Not processed" and their verdict menu is disabled.
- **A claim position that does not fit the text:** the claim moves to "Unplaced claims" in its section (or "Claims outside the supplied assessment") with a warning. Other highlights do not shift.
- **An excerpt position that does not fit:** that excerpt is replaced by a note; the rest of the claim is shown.
- **Anything wrong with the whole reply** (bad JSON, wrong schema version, wrong `request_id`, duplicate claim id): an error screen, and no audit is shown.

## Saved eval items

The [Eval item view](../reference/eval-ui.md#items-and-saved-review) replays a saved
request and response in the same review panes. Selection, evidence expansion and
verdict navigation remain available; they neither edit saved results nor call an
audit service. There is no upload action in this read-only view. Gold annotations
appear in a separate collapsible panel, without changing assessment highlights.

Failed items show saved error details instead of review panes. Invalid or stale saved
responses show the normal validation error screen. The current 1.2.0 contract pin
rejects saved 1.0.0 and 1.1.0 responses.
There is no replay compatibility layer. Lists, metrics and comparisons are separate
from this validation and remain inspectable.

## Known limits

- Section numbers differ: the warnings banner counts from 0; unlabelled cards count from 1.
- A claim whose span overlaps an earlier claim shows as plain text and is not listed under "Unplaced claims". It is reachable only from verdict navigation.
- A `partial` status does not mark claims. Only the banner and the section label show it.
- Backend `span_out_of_range` warnings are not linked to claim badges. The app does its own check.
- Colour-blindness has not been tested.
