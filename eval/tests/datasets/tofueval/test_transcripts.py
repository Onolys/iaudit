"""Fictional transcripts retain source identity and deterministic turn boundaries."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).with_name("fixtures")
MODULE = Path(__file__).resolve().parents[3] / "datasets/tofueval/transcripts.py"
SCHEMA = MODULE.parents[3] / "docs/contracts/audit-request.schema.json"


def load_transcripts():
    assert MODULE.is_file(), "TofuEval transcript builders are not implemented"
    spec = importlib.util.spec_from_file_location("tofueval_transcripts", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_schema_turns(turns):
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator(schema).validate({
        "schema_version": schema["properties"]["schema_version"]["const"],
        "transcript": turns,
        "assessment": [{"id": "s0", "text": "Fictional summary."}],
    })


def test_mediasum_fixture_maps_parallel_arrays_verbatim():
    transcripts = load_transcripts()
    with zipfile.ZipFile(FIXTURES / "mediasum/test_data.zip") as archive:
        records = [json.loads(line) for line in archive.read("test_data.txt").splitlines()]
    for record in records:
        turns = transcripts.build_mediasum_turns(record["speaker"], record["utt"])
        assert [(turn["speaker"], turn["text"]) for turn in turns] == list(
            zip(record["speaker"], record["utt"], strict=True)
        )
        assert [turn["id"] for turn in turns] == [f"t{i}" for i in range(len(turns))]
        assert all(set(turn) == {"id", "speaker", "text"} for turn in turns)
        assert_schema_turns(turns)


def test_mediasum_unicode_whitespace_and_repeated_labels_are_not_changed():
    transcripts = load_transcripts()
    turns = transcripts.build_mediasum_turns(
        [" Unidentified Male ", " Unidentified Male "], ["🪁 e\u0301\n\t", ""]
    )
    assert turns == [
        {"id": "t0", "speaker": " Unidentified Male ", "text": "🪁 e\u0301\n\t"},
        {"id": "t1", "speaker": " Unidentified Male ", "text": ""},
    ]
    assert_schema_turns(turns)


@pytest.mark.parametrize("speakers,utterances", [(["A"], []), ([""], ["text"]), ([" \t"], ["text"])])
def test_mediasum_rejects_unpaired_or_empty_speakers(speakers, utterances):
    transcripts = load_transcripts()
    with pytest.raises(ValueError):
        transcripts.build_mediasum_turns(speakers, utterances)


def test_meetingbank_packs_greedily_at_sixty_words_without_splitting_sentences():
    transcripts = load_transcripts()
    thirty = " ".join(["kite"] * 29 + ["kite."])
    sixty_one = " ".join(["balloon"] * 60 + ["balloon!"])
    blob = f"  {thirty}\n\t{thirty}   Next?\n{sixty_one}\tLast.  "
    turns = transcripts.build_meetingbank_turns(blob)
    assert turns == [
        {"id": "t0", "speaker": "unlabeled", "text": f"{thirty} {thirty}"},
        {"id": "t1", "speaker": "unlabeled", "text": "Next?"},
        {"id": "t2", "speaker": "unlabeled", "text": sixty_one},
        {"id": "t3", "speaker": "unlabeled", "text": "Last."},
    ]
    assert_schema_turns(turns)


def test_meetingbank_fixture_reconstructs_collapsed_whitespace_and_long_sentences():
    transcripts = load_transcripts()
    records = [json.loads(line) for line in (FIXTURES / "meetingbank/test.json").read_text().splitlines()]
    for record in records:
        turns = transcripts.build_meetingbank_turns(record["transcript"])
        assert " ".join(turn["text"] for turn in turns) == " ".join(record["transcript"].split())
        assert_schema_turns(turns)
    turns = transcripts.build_meetingbank_turns(records[0]["transcript"])
    assert [len(turn["text"].split()) for turn in turns] == [6, 70, 35, 35]


def test_meetingbank_normalizes_internal_whitespace_without_unicode_normalization():
    transcripts = load_transcripts()
    assert transcripts.build_meetingbank_turns("  Café\t e\u0301\n🪁 stays.  ") == [
        {"id": "t0", "speaker": "unlabeled", "text": "Café e\u0301 🪁 stays."}
    ]


def test_cache_loads_lazily_once_and_memoises_documents_without_sharing_mutations(tmp_path, monkeypatch):
    transcripts = load_transcripts()
    path = tmp_path / "transcripts.json"
    cache = transcripts.TranscriptCache(path)
    path.write_text(json.dumps({
        "mediasum:same": {"speaker": ["Host"], "utt": ["Kites."]},
        "meetingbank:same": {"transcript": "Balloons."},
    }))
    turns = cache.turns("mediasum", "same")
    assert turns == [{"id": "t0", "speaker": "Host", "text": "Kites."}]
    turns[0]["text"] = "Caller mutation"
    path.unlink()

    def unexpected_rebuild(*args):
        raise AssertionError("A memoised document was rebuilt")

    monkeypatch.setattr(transcripts, "build_mediasum_turns", unexpected_rebuild)
    assert cache.turns("mediasum", "same")[0]["text"] == "Kites."
    assert cache.turns("meetingbank", "same") == [
        {"id": "t0", "speaker": "unlabeled", "text": "Balloons."}
    ]
    with pytest.raises(KeyError, match="missing"):
        cache.turns("meetingbank", "missing")
    with pytest.raises(ValueError, match="dataset"):
        cache.turns("unknown", "same")


def test_process_cache_facade_reads_each_data_directory_once(tmp_path):
    transcripts = load_transcripts()
    for name, text in [("first", "Kites."), ("second", "Balloons.")]:
        data_dir = tmp_path / name
        path = data_dir / "derived/transcripts.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"meetingbank:doc": {"transcript": text}}))
        assert transcripts.get_transcript_turns(data_dir, "meetingbank", "doc")[0]["text"] == text
        path.unlink()
        assert transcripts.get_transcript_turns(data_dir, "meetingbank", "doc")[0]["text"] == text
