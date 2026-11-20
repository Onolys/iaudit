"""Resume callbacks describe saved statuses, including retries that stay failed."""

import pytest
from fakes.fake_backend import FakeBackend
from fakes.synthetic import engine_dataset

from iaudit_eval import store
from iaudit_eval.client import AuditClient
from iaudit_eval.engine import Selection, resume, start_run


@pytest.mark.parametrize("mode,script,abort,expected", [
    ("500", [], False, (1, 7)),
    ("ok", [], False, (8, 0)),
    ("500", ["ok", "500", "ok"], False, (3, 5)),
    ("ok", [], True, (2, 6)),
    ("500", [], True, (1, 7)),
])
async def test_resume_progress_matches_saved_statuses_after_each_retry(
    tmp_path, mode, script, abort, expected,
):
    dataset = engine_dataset()
    first_backend = FakeBackend("500", script=["ok"])
    async with AuditClient("http://fake", transport=first_backend.transport()) as client:
        first = start_run(dataset, Selection(split="all"), base_url="http://fake",
                          runs_root=tmp_path, client=client, on_finish=None)
        await first.wait()
    snapshots = []

    def progress(value):
        saved = store.progress(tmp_path, value.run_id)
        snapshots.append(((value.done, value.failed, value.total, value.cost_usd),
                          (saved["done"], saved["failed"], saved["total"], saved["cost_usd"])))
        if abort:
            resumed.abort()

    backend = FakeBackend(mode, script=script)
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        resumed = resume(first.run_id, runs_root=tmp_path, client=client, concurrency=1,
                         on_progress=progress, on_finish=None)
        assert await resumed.wait() == ("aborted" if abort else "finished")
    assert snapshots
    assert all(actual[:3] == saved[:3] for actual, saved in snapshots), snapshots
    assert all(actual[3] == pytest.approx(saved[3]) for actual, saved in snapshots)
    totals = store.compute_totals(tmp_path, first.run_id)
    assert (totals["ok"], totals["failed"]) == expected
    assert backend.count == (1 if abort else 7)
