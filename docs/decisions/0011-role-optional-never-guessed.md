# 0011. Role is optional and never guessed

**Audience:** contributors.

**Status:** accepted.

Amended by [ADR 0016](0016-contract-reset-0-0-1-groups-optional-speaker-error-details.md): the same rule applies to speaker identity.

**Context.** Real transcripts often lack speaker roles.

**Decision.** A turn with no `role` stays without one. Checks that need a role are skipped for it, a `ambiguous_speaker` warning is added, and the result is often `insufficient_evidence`.

The same applies to `speaker`: it is optional, missing means unknown, and neither an identity nor a placeholder is invented. Speaker-dependent checks and question/answer pairing skip turns without speaker identity. A claim citing a turn without speaker or role receives `ambiguous_speaker`.

**Alternatives.** Infer the role from the speaker or the previous turn.

**Consequences.** The audit never states something about who spoke that the input did not say. Some claims are left undecided.
