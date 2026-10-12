"""03 optional: no 8-word window of the few-shot / prompt examples may appear in eval data."""

import json
import re
import tomllib
from pathlib import Path

from iaudit_backend.prep.prompt import EXAMPLES as PREP_EXAMPLES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "iaudit_backend"
PROMPTS = SRC / "prompts"
CONFIG = tomllib.loads((ROOT / "eval" / "leakage.toml").read_text(encoding="utf-8"))
EVAL_DIRS = [ROOT / d for d in CONFIG["scored_dirs"]]
N = CONFIG["window"]
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


def prompt_files():
    return sorted(p for g in CONFIG["prompt_globs"] for p in SRC.glob(g))


def prompt_texts():
    texts = list(PREP_EXAMPLES)
    for p in prompt_files():
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


def test_link_and_check_fewshot_files_are_scanned_and_clean():
    names = {p.name for p in PROMPTS.glob("*_fewshot.json")}
    assert {"atomize_fewshot.json", "link_fewshot.json", "check_fewshot.json"} <= names
    for name in ("link_fewshot.json", "check_fewshot.json"):
        texts = list(strings(json.loads((PROMPTS / name).read_text(encoding="utf-8"))))
        assert shared(texts, eval_texts()) == set(), name


def test_config_names_the_eight_word_window_and_includes_the_atomize_fewshot():
    assert N == 8
    assert "atomize_fewshot.json" in {p.name for p in prompt_files()}


def speakers(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("speaker", "subject_speaker", "source") and isinstance(v, str):
                yield v
            yield from speakers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from speakers(v)


def test_example_speakers_never_use_the_scored_ids():
    scored = set(CONFIG["scored_speaker_ids"])
    for p in prompt_files():
        used = set(speakers(json.loads(p.read_text(encoding="utf-8"))))
        assert not used & scored, (p.name, used & scored)


def test_a_seeded_scored_speaker_id_is_caught():
    assert set(speakers({"turns": [{"speaker": "alex1"}]})) & set(CONFIG["scored_speaker_ids"])
