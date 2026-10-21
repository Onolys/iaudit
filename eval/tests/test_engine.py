import asyncio
import dataclasses
import json

import httpx
import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import contracts, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import RunProgress, Selection, start_run

URL = "http://fake"


@pytest.fixture(scope="module")
def synth():
    return load("synthetic")


async def _nosleep(_s):
    return None


def _client(fb_or_transport):
    t = fb_or_transport.transport() if hasattr(fb_or_transport, "transport") else fb_or_transport
    return AuditClient(URL, transport=t, sleep=_nosleep)


async def _run(ds, fb, tmp_path, *, sel=None, **kw):
    kw.setdefault("client", _client(fb))
    h = start_run(ds, sel or Selection(split="all"), base_url=URL, runs_root=tmp_path, **kw)
    await h.wait()
    return h


def _items(tmp_path, h):
    return {i["item_id"]: i for i in store.iter_items(tmp_path, h.run_id)}


async def test_full_run_writes_valid_items(synth, tmp_path):
    fb = FakeBackend("ok")
    h = await _run(synth, fb, tmp_path, tags={"contamination": "none"}, max_cost_usd=5.0)
    assert h.state == "finished"
    items = _items(tmp_path, h)
    assert len(items) == 8 and fb.count == 8
    run = store.load_run(tmp_path, h.run_id)
    assert run["state"] == "finished" and run["finished_at"]
    assert run["totals"]["ok"] == 8 and run["totals"]["failed"] == 0
    assert run["totals"] == store.compute_totals(tmp_path, h.run_id)
    assert run["schema_version"] == contracts.schema_version()
    assert run["fingerprint"]["models"] and run["fingerprint"]["prompt_hashes"]
    assert run["concurrency"] == 4 and run["max_cost_usd"] == 5.0
    assert run["tags"] == {"contamination": "none"}
    assert run["backend_url"] == URL and run["dataset"] == "synthetic"
    assert run["dataset_version"] == synth.meta.dataset_version
    assert "git_commit" in run and "git_dirty" in run and "git_diff_sha256" in run
    assert sorted(run["item_ids"]) == sorted(items)
    for iid, it in items.items():
        assert it["status"] == "ok" and it["response_status"] == "complete"
        assert it["request"]["request_id"] == iid  # adapter-supplied id is kept
        assert contracts.validate_request(it["request"]) == []
        assert contracts.validate_response(it["response"]) == []
        assert it["run_info"] and it["failure"] is None and it["attempts"] == 1
        assert it["latency_ms"] >= 0 and it["started_at"] and it["finished_at"]


async def test_lock_released_after_run(synth, tmp_path):
    h = await _run(synth, FakeBackend("ok"), tmp_path)
    with store.RunLock(tmp_path, h.run_id):
        pass


async def test_lock_held_during_run(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.05)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb))  # fmt: skip
    await asyncio.sleep(0.02)
    assert store.is_locked(tmp_path, h.run_id)
    assert store.effective_state(tmp_path, h.run_id) == "running"
    await h.wait()
    assert not store.is_locked(tmp_path, h.run_id)


async def test_preflight_bad_request_zero_posts(synth, tmp_path):
    class Bad:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, n):
            return getattr(self._inner, n)

        def to_request(self, item):
            req = self._inner.to_request(item)
            if item.id == sorted(i.id for i in self._inner.items("dev"))[-1]:
                req = {k: v for k, v in req.items() if k != "assessment"}
            return req

    ds = dataclasses.replace(synth, adapter=Bad(synth.adapter))
    fb = FakeBackend("ok")
    h = await _run(ds, fb, tmp_path, sel=Selection(split="dev"))
    assert h.state == "failed" and fb.count == 0
    run = store.load_run(tmp_path, h.run_id)
    assert run["state"] == "failed" and run["error"]["kind"] == "preflight"
    assert list(store.iter_items(tmp_path, h.run_id)) == []


async def test_preflight_adapter_exception_zero_posts(synth, tmp_path):
    class Boom:
        def __getattr__(self, n):
            return getattr(synth.adapter, n)

        def to_request(self, item):
            raise ValueError("SECRET-TEXT")

    fb = FakeBackend("ok")
    h = await _run(dataclasses.replace(synth, adapter=Boom()), fb, tmp_path)
    assert h.state == "failed" and fb.count == 0
    assert "SECRET-TEXT" not in json.dumps(store.load_run(tmp_path, h.run_id))


@pytest.mark.parametrize(
    ("status", "expect"),
    [(None, "ready"), ("not_downloaded", None), ("failed", None), ("downloading", None)],
)
async def test_preflight_dataset_ready(synth, tmp_path, status, expect):
    meta = dataclasses.replace(synth.meta, data_required=True)
    ds = dataclasses.replace(synth, meta=meta)
    data = tmp_path / "data"
    if status is not None:
        (data / "synthetic").mkdir(parents=True)
        (data / "synthetic" / "download.json").write_text(json.dumps({"status": status}))
    fb = FakeBackend("ok")
    h = await _run(ds, fb, tmp_path / "runs", data_root=data)
    assert h.state == "failed" and fb.count == 0
    assert store.load_run(tmp_path / "runs", h.run_id)["error"]["kind"] == "dataset_not_ready"


async def test_preflight_dataset_ready_passes(synth, tmp_path):
    ds = dataclasses.replace(synth, meta=dataclasses.replace(synth.meta, data_required=True))
    data = tmp_path / "data"
    (data / "synthetic").mkdir(parents=True)
    (data / "synthetic" / "download.json").write_text(json.dumps({"status": "ready"}))
    h = await _run(ds, FakeBackend("ok"), tmp_path / "runs", data_root=data)
    assert h.state == "finished"


async def test_item_failures_have_right_kind(synth, tmp_path):
    fb = FakeBackend("ok", script=["ok", "invalid_error_body", "bad_body", "mismatched_id"])
    h = await _run(synth, fb, tmp_path, concurrency=1)
    assert h.state == "finished"
    items = _items(tmp_path, h)
    order = sorted(items)
    kinds = [items[i]["failure"]["kind"] if items[i]["failure"] else None for i in order]
    assert kinds[:4] == [None, "error_body", "invalid_response", "request_id_mismatch"]
    assert items[order[1]]["failure"]["http_status"] == 500
    assert all(items[i]["status"] == "failed" and items[i]["response"] is None
               for i in order[1:4])  # fmt: skip
    t = store.load_run(tmp_path, h.run_id)["totals"]
    assert t["ok"] == 5 and t["failed"] == 3


async def test_canary_fatal_unsupported_version(synth, tmp_path):
    fb = FakeBackend("unsupported_version")
    h = await _run(synth, fb, tmp_path)
    assert h.state == "failed" and fb.count == 1
    run = store.load_run(tmp_path, h.run_id)
    assert run["error"]["kind"] == "canary_failed"
    assert run["error"]["code"] == "unsupported_version"
    assert run["totals"]["missing"] == 7


async def test_canary_fatal_connection_refused(synth, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    h = await _run(synth, httpx.MockTransport(handler), tmp_path)
    assert h.state == "failed"
    assert store.load_run(tmp_path, h.run_id)["error"]["kind"] == "canary_failed"
    assert len(calls) == 2  # client's single connect retry, no fan-out


async def test_canary_ordinary_failure_not_fatal(synth, tmp_path):
    fb = FakeBackend("ok", script=["timeout"])
    h = await _run(synth, fb, tmp_path)
    assert h.state == "finished" and fb.count == 8
    t = store.load_run(tmp_path, h.run_id)["totals"]
    assert t["failed"] == 1 and t["ok"] == 7


async def test_partial_stored_ok(synth, tmp_path):
    class P(FakeBackend):
        def build_response(self, raw, mode="ok"):
            b = super().build_response(raw, mode)
            b["status"] = "partial"
            b["warnings"] = [{"code": "section_not_processed", "message": "x", "section_index": 0}]
            return b

    fb = P("ok")
    h = await _run(synth, fb, tmp_path)
    items = _items(tmp_path, h)
    assert all(i["status"] == "ok" and i["response_status"] == "partial" for i in items.values())
    assert store.load_run(tmp_path, h.run_id)["totals"]["partial"] == 8


async def test_abort_lets_in_flight_finish(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.05)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  concurrency=2, client=_client(fb))  # fmt: skip
    await asyncio.sleep(0.12)
    h.abort()
    await h.wait()
    assert h.state == "aborted"
    assert store.load_run(tmp_path, h.run_id)["state"] == "aborted"
    n = len(_items(tmp_path, h))
    assert 0 < n < 8 and n == fb.count and fb.in_flight == 0
    assert all(i["status"] == "ok" for i in _items(tmp_path, h).values())
    assert not store.is_locked(tmp_path, h.run_id)


@pytest.mark.parametrize("conc", [1, 2, 4])
async def test_concurrency_cap(synth, tmp_path, conc):
    fb = FakeBackend("ok", delay=0.03)
    h = await _run(synth, fb, tmp_path, concurrency=conc)
    assert h.state == "finished"
    assert fb.max_in_flight == conc


async def test_default_concurrency_never_over_four(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.03)
    await _run(synth, fb, tmp_path)
    assert fb.max_in_flight == 4


async def test_progress_and_on_finish(synth, tmp_path):
    seen: list[RunProgress] = []
    fin = []

    def on_finish(run_id):
        fin.append((run_id, store.load_run(tmp_path, run_id)["state"]))

    h = await _run(synth, FakeBackend("ok"), tmp_path, on_progress=seen.append,
                   on_finish=on_finish)  # fmt: skip
    assert fin == [(h.run_id, "finished")]
    assert seen and all(isinstance(p, RunProgress) and p.run_id == h.run_id for p in seen)
    last = seen[-1]
    assert (last.done, last.failed, last.total, last.state) == (8, 0, 8, "finished")
    assert last.cost_usd == pytest.approx(0.08)
    assert [p.done for p in seen] == sorted(p.done for p in seen)


async def test_callback_errors_do_not_break_run(synth, tmp_path):
    def boom(*_a):
        raise RuntimeError("x")

    h = await _run(synth, FakeBackend("ok"), tmp_path, on_progress=boom, on_finish=boom)
    assert h.state == "finished"


async def test_selection_n_and_seed(synth, tmp_path):
    h = await _run(synth, FakeBackend("ok"), tmp_path, sel=Selection(split="all", n=3, seed=7))
    run = store.load_run(tmp_path, h.run_id)
    assert len(run["item_ids"]) == 3 and run["n_requested"] == 3 and run["seed"] == 7
    assert run["split"] == "all"


async def test_logs_contain_no_request_text(synth, tmp_path, caplog):
    caplog.set_level("DEBUG")
    await _run(synth, FakeBackend("ok"), tmp_path)
    req = synth.adapter.to_request(synth.items("all")[0])
    sample = req["assessment"][0]["text"][:30]
    assert sample not in caplog.text


async def test_engine_sets_request_id_when_adapter_gave_none(synth, tmp_path):
    class NoId:
        def __getattr__(self, n):
            return getattr(synth.adapter, n)

        def to_request(self, item):
            req = dict(synth.adapter.to_request(item))
            req.pop("request_id", None)
            return req

    fb = FakeBackend("ok")
    h = await _run(dataclasses.replace(synth, adapter=NoId()), fb, tmp_path)
    assert h.state == "finished"
    for iid, it in _items(tmp_path, h).items():
        assert it["request"]["request_id"] == f"{h.run_id}:{iid}"
        assert it["response"]["request_id"] == f"{h.run_id}:{iid}"
