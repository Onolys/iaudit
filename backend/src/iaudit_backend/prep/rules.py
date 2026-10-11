"""R2: deterministic dialogue-act rules. Every unsure case resolves to no act."""

import re

from iaudit_backend.models import Turn

from .models import Act, IndexedTurn

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_STRIP = re.compile(r"[^\w\s'\-]")
_WH = {"who", "what", "when", "where", "why", "how", "which"}
_AUX = {"do", "does", "did", "is", "are", "was", "were", "can", "could", "would", "have", "has"}
_SUBJ = {
    "you", "i", "we", "he", "she", "they", "it", "there", "this", "that", "any", "anyone",
    "anything", "your", "my", "his", "her", "the", "a", "some",
}  # fmt: skip
_PERSON = {"you", "i", "we", "he", "she", "they", "anyone"}
_ELICIT = ("tell me", "describe", "walk me through", "can you tell me")
_TAG = re.compile(r"(?:^|[,;\-—]\s*)(?:you know|right|y'know|okay|ok|yeah|eh)\s*\?+$")
_CONTINUERS = {
    "hm", "hmm", "hmmm", "mm", "mmm", "mhm", "mm hm", "mm hmm", "uh huh", "right", "okay", "ok",
    "i see", "got it", "sure",
}  # fmt: skip
_POLAR = {"yeah", "yes", "no", "nope", "yep", "yup"}
_CORRECTION = (
    "actually", "i mean", "no wait", "sorry", "let me correct", "what i meant", "scratch that",
    "i misspoke", "rather",
)  # fmt: skip
_HYPO_OPEN = ("suppose", "imagine", "let's say", "say", "what if", "if")
_MODAL = re.compile(r"\b(?:would|could|might|should|may)\b|'d\b")


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = _STRIP.sub(" ", s).replace("-", " ")
    return " ".join(s.split())


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


def _starts_with(n: str, phrase: str) -> bool:
    return n == phrase or n.startswith(phrase + " ")


def _is_question_sentence(raw: str) -> bool:
    lowered = raw.strip().lower().replace("’", "'")
    n = _norm(raw)
    toks = n.split()
    if not toks:
        return False
    if any(n.startswith(e) for e in _ELICIT):
        return True
    if toks[0] in _AUX and len(toks) >= 2:
        # "Do it later." is an imperative: bare "do" needs a person subject.
        if toks[1] in (_PERSON if toks[0] == "do" else _SUBJ):
            return True
    if toks[0] in _WH and any(t in _AUX for t in toks[1:4]):
        return True
    if lowered.endswith("?"):
        return not _TAG.search(lowered)
    return False


def _is_question(text: str) -> bool:
    return any(_is_question_sentence(s) for s in _sentences(text))


def _is_correction(text: str) -> bool:
    return any(any(_starts_with(_norm(s), m) for m in _CORRECTION) for s in _sentences(text))


def _is_hypothetical(text: str) -> bool:
    for s in _sentences(text):
        n = _norm(s)
        if any(_starts_with(n, o) for o in _HYPO_OPEN) and _MODAL.search(
            s.lower().replace("’", "'")
        ):
            return True
    return False


def _pure_continuer(text: str) -> bool:
    n = _norm(text)
    return bool(n) and len(n.split()) <= 3 and n in _CONTINUERS


def _polar_only(text: str) -> bool:
    toks = _norm(text).split()
    return 1 <= len(toks) <= 2 and all(t in _POLAR for t in toks)


def index_turns(turns: list[Turn]) -> list[IndexedTurn]:
    """Turn index plus rule-based acts (no pairing; see pairing.py)."""
    questions = [_is_question(t.text) for t in turns]
    out: list[IndexedTurn] = []
    for i, t in enumerate(turns):
        acts: set[Act] = set()
        if questions[i]:
            acts.add(Act.question)
        after_question = i > 0 and questions[i - 1] and turns[i - 1].speaker != t.speaker
        if _pure_continuer(t.text):
            acts.add(Act.backchannel)
        elif _polar_only(t.text):
            acts.add(Act.answer if after_question else Act.backchannel)
        elif after_question and not questions[i]:
            acts.add(Act.answer)
        if _is_correction(t.text):
            acts.add(Act.correction)
        if _is_hypothetical(t.text):
            acts.add(Act.hypothetical)
        out.append(
            IndexedTurn(
                index=i,
                id=t.id,
                speaker=t.speaker,
                role=t.role,
                text=t.text,
                length=len(t.text),
                acts=frozenset(acts),
            )
        )
    return out


_MID_CORRECTION = re.compile(r"\b(?:actually|i mean|rather|sorry|scratch that|i misspoke)\b")
_MID_HYPO = re.compile(r"\b(?:if|would)\b")


def unsure_acts(turns: list[Turn], indexed: list[IndexedTurn]) -> dict[int, frozenset[Act]]:
    """Per turn, the act kinds the rules could not decide (R2 "unsure" column).

    Only these kinds go to the LLM; a turn the rules decided on every kind is never sent.
    """
    out: dict[int, frozenset[Act]] = {}
    for t, it in zip(turns, indexed, strict=True):
        text = t.text.lower().replace("\u2019", "'")
        kinds: set[Act] = set()
        if Act.question not in it.acts:
            sents = _sentences(t.text)
            tag_only = all(_TAG.search(s.strip().lower()) for s in sents if "?" in s)
            if ("?" in t.text and not tag_only) or any(
                _norm(s).split()[:1] and _norm(s).split()[0] in (_AUX | _WH) for s in sents
            ):
                kinds.add(Act.question)
        if Act.correction not in it.acts and _MID_CORRECTION.search(text):
            kinds.add(Act.correction)
        if Act.hypothetical not in it.acts and _MID_HYPO.search(text):
            kinds.add(Act.hypothetical)
        if kinds:
            out[it.index] = frozenset(kinds)
    return out
