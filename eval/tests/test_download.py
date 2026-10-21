"""Download framework tests. MockTransport only; no real network."""

import hashlib
import json
import stat

import httpx
import pytest

from iaudit_eval import download as dl
from iaudit_eval.datasets.base import Dataset, DatasetMeta

BODY = b"fictional file bytes " * 100
SHA = hashlib.sha256(BODY).hexdigest()


class Adapter:
    def items(self, split):
        return []


def make_ds(sources, data_required=True, adapter=None, name="fake"):
    return Dataset(
        DatasetMeta(name=name, data_required=data_required, sources=tuple(sources)),
        adapter or Adapter(),
    )


def src(**kw):
    d = {"id": "main", "url": "https://example.test/f.bin", "filename": "f.bin"}
    d.update(kw)
    return d


class Counter:
    def __init__(self, body=BODY, status=200):
        self.n = 0
        self.body = body
        self.status = status

    def __call__(self, request):
        self.n += 1
        return httpx.Response(self.status, content=self.body)

    @property
    def transport(self):
        return httpx.MockTransport(self)


def run(ds, tmp_path, c):
    return dl.download(ds, data_root=tmp_path, transport=c.transport)


def test_not_downloaded_by_default(tmp_path):
    ds = make_ds([src()])
    assert dl.status(ds, data_root=tmp_path)["status"] == "not_downloaded"
    assert not dl.is_ready(ds, data_root=tmp_path)


def test_download_ready_with_sha(tmp_path):
    c = Counter()
    ds = make_ds([src()])
    st = run(ds, tmp_path, c)
    assert st["status"] == "ready"
    f = st["files"][0]
    assert f["sha256"] == SHA and f["size_bytes"] == len(BODY)
    assert f["id"] == "main" and f["filename"] == "f.bin" and f["fetched_at"]
    assert (tmp_path / "fake" / "f.bin").read_bytes() == BODY
    assert not list((tmp_path / "fake").glob("*.part"))
    on_disk = json.loads((tmp_path / "fake" / "download.json").read_text())
    assert on_disk["status"] == "ready" and on_disk["updated_at"]
    assert stat.S_IMODE((tmp_path / "fake" / "download.json").stat().st_mode) == 0o600
    assert dl.is_ready(ds, data_root=tmp_path)


def test_pinned_match_ok(tmp_path):
    st = run(make_ds([src(sha256=SHA)]), tmp_path, Counter())
    assert st["status"] == "ready"


def test_pinned_mismatch_fails(tmp_path):
    ds = make_ds([src(sha256="0" * 64)])
    st = run(ds, tmp_path, Counter())
    assert st["status"] == "failed" and "sha256" in st["error"]
    assert not (tmp_path / "fake" / "f.bin").exists()
    assert not list((tmp_path / "fake").glob("*.part"))
    assert not dl.is_ready(ds, data_root=tmp_path)


def test_rerun_is_noop(tmp_path):
    c = Counter()
    ds = make_ds([src()])
    run(ds, tmp_path, c)
    assert c.n == 1
    st = run(ds, tmp_path, c)
    assert c.n == 1 and st["status"] == "ready"


def test_http_error_fails(tmp_path):
    st = run(make_ds([src()]), tmp_path, Counter(status=404))
    assert st["status"] == "failed" and st["error"]
    assert not (tmp_path / "fake" / "f.bin").exists()


def test_failed_can_retry(tmp_path):
    ds = make_ds([src()])
    run(ds, tmp_path, Counter(status=500))
    st = run(ds, tmp_path, Counter())
    assert st["status"] == "ready" and "error" not in st


def test_size_mismatch_fails(tmp_path):
    st = run(make_ds([src(size_bytes=3)]), tmp_path, Counter())
    assert st["status"] == "failed"


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", ".", "", "/abs"])
def test_bad_filename_fails_without_request(tmp_path, bad):
    c = Counter()
    st = run(make_ds([src(filename=bad)]), tmp_path, c)
    assert st["status"] == "failed" and c.n == 0


def test_bad_url_scheme_fails(tmp_path):
    c = Counter()
    st = run(make_ds([src(url="file:///etc/passwd")]), tmp_path, c)
    assert st["status"] == "failed" and c.n == 0


def test_progress_callback(tmp_path):
    calls = []
    dl.download(
        make_ds([src()]),
        data_root=tmp_path,
        transport=Counter().transport,
        progress=lambda *a: calls.append(a),
    )
    assert calls and calls[-1][1] == len(BODY)


def test_post_download_hook_runs_and_failure_fails(tmp_path):
    seen = []

    class A(Adapter):
        def post_download(self, data_dir):
            seen.append(sorted(p.name for p in data_dir.iterdir()))

    st = run(make_ds([src()], adapter=A()), tmp_path, Counter())
    assert st["status"] == "ready" and "f.bin" in seen[0]

    class B(Adapter):
        def post_download(self, data_dir):
            raise ValueError("boom")

    st = run(make_ds([src()], adapter=B(), name="other"), tmp_path, Counter())
    assert st["status"] == "failed" and "boom" in st["error"]


def test_adapter_download_override(tmp_path):
    class A(Adapter):
        def download(self, data_dir, progress):
            (data_dir / "x.txt").write_bytes(b"hi")
            return [
                dl.FileRecord(
                    id="x",
                    filename="x.txt",
                    sha256=hashlib.sha256(b"hi").hexdigest(),
                    size_bytes=2,
                    fetched_at="2026-01-01T00:00:00Z",
                )
            ]

    c = Counter()
    st = run(make_ds([src()], adapter=A()), tmp_path, c)
    assert st["status"] == "ready" and c.n == 0
    assert st["files"][0]["id"] == "x"


def test_require_ready(tmp_path):
    ds = make_ds([src()])
    with pytest.raises(dl.DatasetNotReady):
        dl.require_ready(ds, data_root=tmp_path)
    run(ds, tmp_path, Counter())
    dl.require_ready(ds, data_root=tmp_path)


def test_require_ready_skips_when_not_required(tmp_path):
    dl.require_ready(make_ds([], data_required=False), data_root=tmp_path)


def test_unpinned_change_on_disk_warns(tmp_path):
    ds = make_ds([src()])
    run(ds, tmp_path, Counter())
    assert dl.hash_warnings(ds, data_root=tmp_path) == []
    (tmp_path / "fake" / "f.bin").write_bytes(b"tampered")
    w = dl.hash_warnings(ds, data_root=tmp_path)
    assert len(w) == 1 and "f.bin" in w[0] and "tampered" not in w[0]


def test_changed_file_triggers_refetch_with_warning(tmp_path):
    ds = make_ds([src()])
    run(ds, tmp_path, Counter())
    (tmp_path / "fake" / "f.bin").write_bytes(b"tampered")
    st = run(ds, tmp_path, Counter(body=b"new upstream bytes"))
    assert st["status"] == "ready"
    assert st["files"][0]["sha256"] == hashlib.sha256(b"new upstream bytes").hexdigest()
    w = dl.hash_warnings(ds, data_root=tmp_path)
    assert len(w) == 1 and "changed" in w[0]
