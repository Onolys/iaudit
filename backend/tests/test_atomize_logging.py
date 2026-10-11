import logging

from atomize_helpers import ROSTER, raw

from iaudit_backend.atomize import atomize_section
from iaudit_backend.atomize.models import AtomizerOutput
from iaudit_backend.llm import FailingClient, LLMResult, LLMUnavailable
from iaudit_backend.models import Section, Turn
from iaudit_backend.prep import prep

CANARIES = ["zebracanary", "quokkaproposition", "wombatsegment", "narwhalturn"]


class Scripted:
    def __init__(self, *outs):
        self.outs, self.n = list(outs), 0

    async def complete_json(self, req, metrics=None):
        self.n += 1
        return LLMResult(
            parsed=AtomizerOutput.model_validate(self.outs[min(self.n, len(self.outs)) - 1])
        )


def logged(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "iaudit"]


async def test_prep_logs_counts_only(make_ctx, caplog):
    turns = [
        Turn(id="1", speaker="a", text="Do you narwhalturn?"),
        Turn(id="2", speaker="b", text="Yes narwhalturn."),
    ]
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await prep(turns, make_ctx())
    (line,) = [m for m in logged(caplog) if m.startswith("prep ")]
    assert "turns=2" in line and "pairs=1" in line and 'request_id="r1"' in line
    assert "narwhalturn" not in caplog.text


async def test_atomize_logs_counts_for_success_retry_and_failure(make_ctx, caplog):
    text = "zebracanary misplaces receipts. Jordan double-books clients every single day."
    bad = {
        "claims": [
            raw(
                ref="a",
                segments=["zebracanary misplaces receipts"],
                proposition="quokkaproposition",
            ),
            raw(ref="b", segments=["wombatsegment missing here"]),
        ]
    }
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        ok = await atomize_section(
            Section(id="s", text=text), ROSTER, make_ctx(llm=Scripted(bad, bad)), index=4
        )
        failed = await atomize_section(
            Section(id="s", text=text),
            ROSTER,
            make_ctx(llm=FailingClient(LLMUnavailable("zebracanary down"))),
            index=5,
        )
    lines = [m for m in logged(caplog) if m.startswith("atomize_section")]
    assert len(lines) == 2
    first, second = lines
    assert "section_index=4" in first and "claims=1" in first and "dropped=1" in first
    assert "retries=1" in first and "gaps=1" in first and "failure" not in first
    assert 'failure="unavailable"' in second and "section_index=5" in second
    assert ok.status == "ok" and failed.status == "failed"
    for c in CANARIES:
        assert c not in caplog.text, c


async def test_failure_reasons_are_fixed_codes_not_text(make_ctx, caplog):
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        res = await atomize_section(
            Section(id="s", text="zebracanary has nothing usable here at all."),
            ROSTER,
            make_ctx(llm=Scripted({"claims": [raw(segments=["wombatsegment nope"])]})),
            index=0,
        )
    assert res.failure in {"no_claims", "too_many_dropped"}
    assert "zebracanary" not in caplog.text and "wombatsegment" not in caplog.text
    assert "zebracanary" not in repr(res.model_dump())


async def test_blank_section_logs_nothing_sensitive(make_ctx, caplog):
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await atomize_section(Section(id="s", text="  "), ROSTER, make_ctx(), index=0)
    assert all("section_index=0" in m or not m for m in logged(caplog))
