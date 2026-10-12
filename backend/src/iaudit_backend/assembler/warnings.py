"""R6: warning construction, in contract order, with fixed templates (never text)."""

from .claims import ClaimEvent

NOT_PROCESSED = {
    "timeout": "Section {i} was not processed: the audit ran out of time for it.",
    "error": "Section {i} was not processed: an internal error occurred.",
    "no_claims_located": "Section {i} was not processed: no claims could be located in it.",
}
AMBIGUOUS = "Speaker role was missing for turn(s) {turns}; no speaker was assumed."
OUT_OF_RANGE = "An evidence or claim span did not fit the input and was omitted."
TRUNCATED = "The input could not be processed in full."
UNLOCATABLE = "A claim in section {i} could not be located in the text and was omitted."
OVERLAP_TRIMMED = "A claim was trimmed to keep claim spans from overlapping."
OVERLAP = "An overlapping claim was omitted to keep claim spans from overlapping."


def section_warning(index: int, reason: str) -> dict:
    return {
        "code": "section_not_processed",
        "message": NOT_PROCESSED[reason].format(i=index + 1),
        "section_index": index,
    }


def claim_warning(code: str, message: str, claim_id: str) -> dict:
    return {"code": code, "message": message, "claim_id": claim_id}


def ambiguous_warning(turns: list[int], claim_id: str) -> dict:
    listed = ", ".join(str(t) for t in sorted(set(turns)))
    return claim_warning("ambiguous_speaker", AMBIGUOUS.format(turns=listed), claim_id)


def event_warning(ev: ClaimEvent, id_of: dict[str, str]) -> dict:
    if ev.kind == "unlocatable":
        return {
            "code": "other",
            "message": UNLOCATABLE.format(i=ev.section_index + 1),
            "section_index": ev.section_index,
        }
    if ev.kind == "overlap_trimmed":
        w = {"code": "other", "message": OVERLAP_TRIMMED}
        if ev.key in id_of:
            w["claim_id"] = id_of[ev.key]
        return w
    w = {"code": "other", "message": OVERLAP}
    if ev.kept_key in id_of:
        w["claim_id"] = id_of[ev.kept_key]
    return w


def truncated_warning() -> dict:
    return {"code": "input_truncated", "message": TRUNCATED}
