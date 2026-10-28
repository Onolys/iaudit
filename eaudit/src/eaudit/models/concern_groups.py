"""Public concern grouping; checked against the response schema by a drift test."""

from .audit import ConcernGroup, ConcernType

GROUP_OF: dict[ConcernType, ConcernGroup] = {
    ConcernType.unsupported_claim: ConcernGroup.not_in_interview,
    ConcernType.unsupported_causal_link: ConcernGroup.not_in_interview,
    ConcernType.question_as_answer: ConcernGroup.not_in_interview,
    ConcernType.unsupported_inference: ConcernGroup.not_in_interview,
    ConcernType.contradictory_evidence: ConcernGroup.opposite_of_interview,
    ConcernType.negation_reversal: ConcernGroup.opposite_of_interview,
    ConcernType.wrong_attribution: ConcernGroup.changed_detail,
    ConcernType.timeframe_mismatch: ConcernGroup.changed_detail,
    ConcernType.quantity_mismatch: ConcernGroup.changed_detail,
    ConcernType.frequency_severity_inflation: ConcernGroup.changed_detail,
    ConcernType.certainty_inflation: ConcernGroup.changed_detail,
    ConcernType.opinion_as_fact: ConcernGroup.changed_detail,
    ConcernType.calculation_error: ConcernGroup.changed_detail,
    ConcernType.meaning_shift: ConcernGroup.changed_detail,
    ConcernType.context_stripping: ConcernGroup.missing_context,
    ConcernType.correction_ignored: ConcernGroup.missing_context,
    ConcernType.conflicting_accounts_flattened: ConcernGroup.missing_context,
}
