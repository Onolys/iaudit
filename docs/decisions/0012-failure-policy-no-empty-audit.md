# 0012. Stalled claims degrade; an audit with nothing usable fails

**Audience:** contributors.

**Status:** accepted.

**Context.** Model calls fail and time runs out. An empty audit would read as "nothing wrong".

**Decision.** A claim whose call fails becomes `insufficient_evidence` with a warning. A section that fails is omitted and the reply is `partial`. If nothing usable finishes, the request fails with 503 (provider unavailable) or 504 (deadline).

**Alternatives.** Always return 200 with whatever finished.

**Consequences.** A 200 always carries real results. Clients must handle 503 and 504.
