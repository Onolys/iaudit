# 0015. Add quantity_mismatch; widen attribution and context stripping

**Audience:** contributors.

**Status:** accepted.

Amended by ADR 0016: contract reset to 0.0.1.

**Context.** The mission lists twelve checks. A stated figure that differs from the interview (a 20 mg dose recorded as 10 mg, a team of ten recorded as twelve) fits none of them well. It is not "more" or "worse", so frequency or severity inflation misdescribes it, and generic contradiction hides a filterable, high-stakes class. Two existing checks are also narrower in code than in the mission: check 3 covers who reported something, which applies equally to a non-person owner such as a previous versus a current medication, and check 8 covers an omitted qualification that changes meaning, which includes a group, setting or condition replaced by a wider one. The mission's exclusion of "numerical score calculations" also needs to say it means scoring rules, not figures the assessment states about interview facts.

**Decision.**
- Add the concern type `quantity_mismatch` as mission check 13 and as the 13th, last value of the concern enum. Evaluation buckets are 1-based enum positions, so appending keeps buckets 1-12 and all existing gold and expected data unchanged.
- Widen `wrong_attribution` to a wrong person, source or entity, and `context_stripping` to a dropped qualifier or broadened scope. This is wording only (mission, prompts, templates). The `experiencer` field value `other_person` is kept.
- Ordinary rounding, including dropped decimals, is not a mismatch. A total is checked only against figures the interview supplies.
- The TofuEval `mapping.json` stays at v1.0.0. Changing it after seeing results would be label drift, so `quantity_mismatch` is reported as a concern not in the mapping (`concern_not_in_mapping_quantity_mismatch`).

**Alternatives.** Fold quantity into `frequency_severity_inflation` or `contradictory_evidence`. Insert the new type next to check 7, which would shift buckets and gold. Keep the arithmetic exclusion as worded. Bump `mapping.json`. Rename the `other_person` value.

**Consequences.** A number error that used to carry `contradictory_evidence` may now carry `quantity_mismatch`, so mapped concern-match can fall in the TofuEval Contradiction group; recall is unaffected because any flag counts. Granular types can be combined later if the data calls for it.
