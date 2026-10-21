# 0008. One synchronous call with a 100 second cap

**Audience:** contributors.

**Status:** accepted.

**Context.** The contract is one request and one response, and the review UI waits for it.

**Decision.** `POST /v1/audit` answers in one call. The audit has a hard cap (`IAUDIT_AUDIT_DEADLINE_S`, 100 s by default) and the UI waits up to 120 s. Claims stream through the stages so the cap is spent on work, not waiting.

**Alternatives.** A job queue with polling or streaming.

**Consequences.** No job state to store, and a simple client. Long transcripts have to fit the cap or return `partial`.
