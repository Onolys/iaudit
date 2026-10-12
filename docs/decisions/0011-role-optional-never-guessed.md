# 0011. Role is optional and never guessed

**Audience:** contributors.

**Status:** accepted.

**Context.** Real transcripts often lack speaker roles.

**Decision.** A turn with no `role` stays without one. Checks that need a role are skipped for it, a `ambiguous_speaker` warning is added, and the result is often `insufficient_evidence`.

**Alternatives.** Infer the role from the speaker or the previous turn.

**Consequences.** The audit never states something about who spoke that the input did not say. Some claims are left undecided.
