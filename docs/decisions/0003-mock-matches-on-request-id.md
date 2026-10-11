# 0003. Mock mode matches on request_id

**Audience:** contributors.

**Status:** accepted.

**Context.** Mock mode needs the right reply for an uploaded file.

**Decision.** Match the upload's `request_id` to a bundled pair exactly. No match is an error, not a fallback.

**Consequences.** A reviewer never sees an audit of a different file. Every mock pair needs a unique `request_id`; a test enforces it.
