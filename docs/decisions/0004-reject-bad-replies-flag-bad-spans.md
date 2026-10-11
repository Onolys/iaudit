# 0004. Reject broken replies; flag bad spans

**Audience:** contributors.

**Status:** accepted.

**Context.** A reply can be wrong in the whole or in one position.

**Decision.** A reply that fails the schema, version, `request_id` or unique-id checks is rejected whole. A single span outside the input flags only its claim or excerpt.

**Consequences.** No half-audits from a broken body, and one bad position does not hide the rest. Matches the contract's consumer rules.
