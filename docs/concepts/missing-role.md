# Missing role

What happens when a transcript turn has no `role`.

**Audience:** users and contributors.

`role` (interviewer, respondent, informant, other) is optional in the contract. The backend **never guesses it**, never copies it from another turn of the same speaker, and never invents a speaker.

When a turn a claim relies on has no role:

- Checks that need to know who is speaking (attribution of a reply to the right person, and a question being taken as an answer) are skipped for that turn.
- The reply carries an `ambiguous_speaker` warning for the claim, naming turn indexes only.
- The result often becomes `insufficient_evidence`, because the audit cannot tell an interviewer's question from a respondent's answer.

Question-and-answer pairing still works without roles, because it uses the `speaker` string only. A transcript with roles everywhere gets the full checks. See [warnings](../reference/warnings.md).
