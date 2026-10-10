# Architecture

High-level design: how the system fits together.

**Audience:** everyone.

v1 is one synchronous JSON exchange. The frontend owns the contract in [contracts/](contracts/). It sends an `AuditRequest` (transcript turns plus assessment sections). The backend returns an `AuditResponse` (claim verdicts, concern types, and positions into that same input). There is no streaming and no background job.

`label` and `score` are display-only. The response locates claims and excerpts by index and character offset. It does not copy transcript text or timestamps.
