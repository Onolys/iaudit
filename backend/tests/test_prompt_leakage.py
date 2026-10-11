"""03 optional: no 8-word window of the few-shot / prompt examples may appear in eval data."""

import json
import re
from pathlib import Path

from iaudit_backend.prep.prompt import EXAMPLES as PREP_EXAMPLES

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "iaudit_backend" / "prompts"
EVAL_DIRS = [ROOT / "eval" / "data", ROOT / "tests" / "data"]
N = 8
_WORD = re.compile(r"[^\W_]+")


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def windows(texts, n=N):
    out = set()
    for t in texts:
        w = _WORD.findall(t.lower())
        out |= {tuple(w[i : i + n]) for i in range(len(w) - n + 1)}
    return out


def shared(a_texts, b_texts):
    return windows(a_texts) & windows(b_texts)


def prompt_texts():
    texts = list(PREP_EXAMPLES)
    for p in sorted(PROMPTS.glob("*_fewshot.json")):
        texts += list(strings(json.loads(p.read_text(encoding="utf-8"))))
    return texts


def eval_texts():
    texts = []
    for d in EVAL_DIRS:
        for p in sorted(d.rglob("*.json*")) if d.exists() else []:
            for line in p.read_text(encoding="utf-8").splitlines() or [""]:
                try:
                    texts += list(strings(json.loads(line)))
                except ValueError:
                    pass
            try:
                texts += list(strings(json.loads(p.read_text(encoding="utf-8"))))
            except ValueError:
                pass
    return texts


def test_fewshot_files_are_marked_as_prompt_split():
    data = json.loads((PROMPTS / "atomize_fewshot.json").read_text(encoding="utf-8"))
    assert data["split"] == "prompt"


def test_eval_corpus_is_found():
    assert len(eval_texts()) > 50  # the ADHD fixtures; guards against a silently empty scan


def test_no_eight_word_window_is_shared_with_eval_data():
    assert shared(prompt_texts(), eval_texts()) == set()


def test_leak_check_catches_a_seeded_copy():
    longest = max(eval_texts(), key=len)
    assert len(_WORD.findall(longest)) >= N
    assert shared(prompt_texts() + [longest], eval_texts()) != set()
