# 0001. The frontend owns the contract

**Audience:** contributors.

**Status:** accepted.

**Context.** Two sides must agree on the audit JSON.

**Decision.** The schemas in [contracts/](../contracts/) are the single source. The frontend imports them (`@contracts`) and never copies them. The backend implements them.

**Consequences.** A contract change updates schemas and docs together and bumps `schema_version`. The UI can run on example data before the backend exists.
