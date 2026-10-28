"""Task 10: cost cap (AC 8), estimate (AC 11), probe."""

import httpx
import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import contracts, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import Selection, probe, resume, start_run
from iaudit_eval.estimate import Estimate, estimate, request_chars

URL = "http://fake"


@pytest.fixture(scope="module")
def synth():
    return load("synthetic")


async def _nosleep(_s):
    return None


def _client(fb):
    return AuditClient(URL, transport=fb.transport(), sleep=_nosleep)


async def _run(ds, fb, tmp_path, **kw):
    h = start_run(ds, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), **kw)  # fmt: skip
    await h.wait()
    return h


# ---------- cost cap (AC 8) ----------

async def test_cap_exceeded_aborts_cost_and_is_resumable(synth, tmp_path):
    fb = FakeBackend("ok", cost_usd=0.01)
    h = await _run(synth, fb, tmp_path, max_cost_usd=0.025, concurrency=1)
    assert h.state == "aborted_cost"
    run = store.load_run(tmp_path, h.run_id)
    assert run["state"] == "aborted_cost" and run["finished_at"]
    assert "error" not in run or not run["error"]
    # cap 0.025, 0.01 each: stops after the 3rd (spent 0.03 >= 0.025)
    assert fb.count == 3 < 8
    assert len(list(store.iter_items(tmp_path, h.run_id))) == 3
    # resumable: new invocation has its own spend; cap raised, finishes the rest
    h2 = resume(h.run_id, max_cost_usd=1.0, runs_root=tmp_path, client=_client(fb))
    assert await h2.wait() == "finished"
    assert fb.count == 8


async def test_cap_in_flight_items_finish(synth, tmp_path):
    fb = FakeBackend("ok", cost_usd=0.01, delay=0.02)
    h = await _run(synth, fb, tmp_path, max_cost_usd=0.02, concurrency=4)
    assert h.state == "aborted_cost"
    # canary (0.01) then up to 4 in flight; all that were sent are stored
    stored = len(list(store.iter_items(tmp_path, h.run_id)))
    assert stored == fb.count and 2 <= stored < 8


async def test_cap_zero_spends_nothing(synth, tmp_path):
    fb = FakeBackend("ok")
    h = await _run(synth, fb, tmp_path, max_cost_usd=0.0)
    assert h.state == "aborted_cost" and fb.count == 0


async def test_resume_honours_cap_per_invocation(synth, tmp_path):
    fb = FakeBackend("ok", cost_usd=0.01)
    h = await _run(synth, fb, tmp_path, max_cost_usd=0.015, concurrency=1)
    assert h.state == "aborted_cost" and fb.count == 2
    # prior spend (0.02) does not count against the new invocation
    h2 = resume(h.run_id, max_cost_usd=0.025, runs_root=tmp_path, client=_client(fb))
    assert await h2.wait() == "aborted_cost"
    assert fb.count == 5  # 3 more


async def test_cap_set_missing_cost_fails_closed(synth, tmp_path):
    fb = FakeBackend("ok")
    fb.script = ["missing_cost"]
    h = await _run(synth, fb, tmp_path, max_cost_usd=5.0, concurrency=1)
    assert h.state == "failed"
    run = store.load_run(tmp_path, h.run_id)
    assert run["state"] == "failed"
    assert run["error"]["kind"] == "cost_missing" and run["error"]["message"]
    assert fb.count == 1  # canary lacked cost: nothing more dispatched


async def test_cap_set_missing_cost_midrun_in_flight_finish(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.02)
    fb.script = ["ok", "missing_cost"]
    h = await _run(synth, fb, tmp_path, max_cost_usd=5.0, concurrency=2)
    assert h.state == "failed"
    assert store.load_run(tmp_path, h.run_id)["error"]["kind"] == "cost_missing"
    assert len(list(store.iter_items(tmp_path, h.run_id))) == fb.count < 8


async def test_no_cap_missing_cost_ignored_silently(synth, tmp_path, caplog):
    fb = FakeBackend("missing_cost")
    h = await _run(synth, fb, tmp_path)
    assert h.state == "finished"
    run = store.load_run(tmp_path, h.run_id)
    assert not run["warnings"] and not run.get("error")
    assert not [r for r in caplog.records if "cost" in r.getMessage().lower()
                and r.levelname in ("WARNING", "ERROR")]  # fmt: skip


# ---------- estimate (AC 11) ----------

def test_estimate_cold_start(synth, tmp_path):
    est = estimate(synth, Selection(split="all"), runs_root=tmp_path)
    assert isinstance(est, Estimate)
    assert est.basis == "none" and est.n_items == 8 and est.rough is True
    assert est.est_input_tokens is None and est.est_output_tokens is None
    assert est.est_cost_usd is None
    assert "run a small N first" in est.note


async def test_estimate_from_prior_runs(synth, tmp_path):
    h = await _run(synth, FakeBackend("ok", cost_usd=0.01), tmp_path)
    items = list(store.iter_items(tmp_path, h.run_id))
    n_in = sum(100 / request_chars(i["request"]) for i in items) / len(items)
    est = estimate(synth, Selection(split="all"), runs_root=tmp_path)
    assert est.basis == "prior_runs" and est.rough is True and est.n_items == 8
    chars = sum(request_chars(i["request"]) for i in items)
    assert est.est_input_tokens == pytest.approx(n_in * chars)
    assert est.est_output_tokens == pytest.approx(
        sum(20 / request_chars(i["request"]) for i in items) / len(items) * chars)
    assert est.est_cost_usd == pytest.approx(
        sum(0.01 / request_chars(i["request"]) for i in items) / len(items) * chars)
    assert est.note


async def test_estimate_subset_scales_and_cost_null_when_unreported(synth, tmp_path):
    await _run(synth, FakeBackend("missing_cost"), tmp_path)
    full = estimate(synth, Selection(split="all"), runs_root=tmp_path)
    half = estimate(synth, Selection(split="all", n=4), runs_root=tmp_path)
    assert full.est_cost_usd is None and half.est_cost_usd is None
    assert half.n_items == 4 and 0 < half.est_input_tokens < full.est_input_tokens


async def test_estimate_ignores_other_dataset_and_failed(synth, tmp_path):
    await _run(synth, FakeBackend("500"), tmp_path)  # only failed items
    est = estimate(synth, Selection(split="all"), runs_root=tmp_path)
    assert est.basis == "none"


# ---------- probe ----------

async def test_probe_accepts_version_zero_audit_work():
    fb = FakeBackend("ok")
    res = await probe(URL, transport=fb.transport())
    assert res.reachable and res.accepts_version
    assert res.backend_schema_version == contracts.schema_version()
    assert fb.audit_work == 0


async def test_probe_version_mismatch():
    fb = FakeBackend("ok", supported_version="9.9.9")
    res = await probe(URL, transport=fb.transport())
    assert res.reachable and not res.accepts_version
    assert res.backend_schema_version == "9.9.9"
    assert fb.audit_work == 0


async def test_probe_unreachable():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    res = await probe(URL, transport=httpx.MockTransport(boom))
    assert res.reachable is False and res.accepts_version is False
    assert res.backend_schema_version is None


async def test_probe_healthz_ok_post_unreachable():
    def h(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ConnectError("refused", request=request)

    res = await probe(URL, transport=httpx.MockTransport(h))
    assert res.reachable is False


@pytest.mark.parametrize("body", [{}, {"schema_version": 7}, {"schema_version": "9.8.7"}])
async def test_probe_unrecognized_body_does_not_accept_version(body):
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(400, json=body)

    result = await probe(URL, transport=httpx.MockTransport(handler))
    assert result.reachable and not result.accepts_version
