"""English-only tokenizer: NFKC, lowercase, stopwords, light stemmer plus a prefix-5 channel."""

import re
import unicodedata

_TOKEN = re.compile(r"[a-z0-9']+")
STOPWORDS = frozenset(
    """a about after all also am an and any are as at be because been before being but by can
    could did do does doing for from had has have having he her hers him his how i if in into is it
    its just me more my of on one or our out over she should so some such than that the their them
    then there these they this those to too up us very was we were what when where which while who
    whom why will with would you your yours""".split()
)  # negators (no, not, never) and numbers are deliberately not stopwords
_SUFFIXES = ("ies", "ing", "ed", "es", "ly", "s")
PREFIX_LEN = 5
MIN_STEM = 3


def stem(tok: str) -> str:
    if tok.endswith("'s"):
        tok = tok[:-2]
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= MIN_STEM:
            base = tok[: -len(suf)]
            return base + "y" if suf == "ies" else base
    return tok


def tokenize(text: str) -> list[str]:
    """Stems plus a `p:` prefix-5 token for long words, so 'forgets' meets 'forgetful'."""
    out: list[str] = []
    for raw in _TOKEN.findall(unicodedata.normalize("NFKC", text).lower()):
        tok = raw.strip("'")
        if not tok or tok in STOPWORDS:
            continue
        out.append(stem(tok))
        if len(tok) > PREFIX_LEN:
            out.append("p:" + tok[:PREFIX_LEN])
    return out
