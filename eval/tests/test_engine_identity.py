"""Schema identity and optional model identity are captured and guarded independently."""

import pytest
from fakes.fake_backend import BASE_HASHES, BASE_MODELS, FakeBackend

from iaudit_eval import contracts, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import (
    FingerprintChanged,
    SchemaVersionChanged,
    Selection,
    resume,
    start_run,
)


class FirstWithoutInfo(FakeBackend):
    def build_response(self, raw, mode="ok"):
        body = super().build_response(raw, mode)
        if self.audit_work == 1:
            body.pop("run_info")
        return body


async def test_later_run_info_captures_fingerprint_and_guards_resume(tmp_path):
    backend = FirstWithoutInfo("500", script=["ok", "ok"])
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        handle = start_run(load("synthetic"), Selection(split="all"), base_url="http://fake",
                           runs_root=tmp_path, client=client, on_finish=None)
        assert await handle.wait() == "finished"
    run = store.load_run(tmp_path, handle.run_id)
    assert run["schema_version"] == contracts.schema_version()
    assert run["fingerprint"] == {"models": BASE_MODELS, "prompt_hashes": BASE_HASHES}
    before = (tmp_path / handle.run_id / "run.json").read_bytes()
    changed = FakeBackend("changed_models")
    async with AuditClient("http://fake", transport=changed.transport()) as client:
        resumed = resume(handle.run_id, runs_root=tmp_path, client=client, on_finish=None)
        with pytest.raises(FingerprintChanged):
            await resumed.wait()
    assert (tmp_path / handle.run_id / "run.json").read_bytes() == before
    assert changed.count == 1


@pytest.mark.parametrize("allow_mixed", [False, True])
async def test_resume_checks_schema_even_without_a_stored_fingerprint(tmp_path, allow_mixed):
    backend = FirstWithoutInfo("500", script=["ok"])
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        handle = start_run(load("synthetic"), Selection(split="all"), base_url="http://fake",
                           runs_root=tmp_path, client=client, on_finish=None)
        await handle.wait()
    assert store.load_run(tmp_path, handle.run_id)["fingerprint"] is None
    store.update_run(tmp_path, handle.run_id, schema_version="0.0.1")
    before = (tmp_path / handle.run_id / "run.json").read_bytes()
    backend = FakeBackend()
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        resumed = resume(handle.run_id, runs_root=tmp_path, client=client,
                         allow_mixed=allow_mixed, on_finish=None)
        with pytest.raises(SchemaVersionChanged):
            await resumed.wait()
    assert backend.count == 1
    assert (tmp_path / handle.run_id / "run.json").read_bytes() == before
