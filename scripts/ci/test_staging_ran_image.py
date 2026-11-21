#!/usr/bin/env python3
"""Unit tests for staging_ran_image.py. Run: python3 scripts/ci/test_staging_ran_image.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import staging_ran_image as m  # noqa: E402

SHA = "33083a5" + "0" * 33
OTHER = "1" * 40
IDX = "sha256:" + "f3d1c1af".ljust(64, "0")
PLAT = "sha256:" + "b7b4aa22".ljust(64, "0")
ATTEST = "sha256:" + "a1a1a1a1".ljust(64, "0")
UNRELATED = "sha256:" + "deadbeef".ljust(64, "0")
REPO = "us-central1-docker.pkg.dev/onolys/onolys/api"
INDEX = {
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {"digest": PLAT, "platform": {"architecture": "amd64", "os": "linux"}},
        {"digest": ATTEST, "platform": {"architecture": "unknown", "os": "unknown"}},
    ],
}
SINGLE = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {}, "layers": []}


def rev(name, image_digest, git_sha, status_digest=None):
    r = {
        "metadata": {"name": name},
        "spec": {"containers": [{"image": f"{REPO}@{image_digest}", "env": [{"name": "X", "value": "1"}, {"name": "GIT_SHA", "value": git_sha}]}]},
    }
    if status_digest:
        r["status"] = {"imageDigest": f"{REPO}@{status_digest}"}
    return r


class Match(unittest.TestCase):
    def test_match_via_platform_digest(self):
        r = rev("a", PLAT, SHA)
        self.assertIs(m.matching_revision(SHA, IDX, INDEX, [rev("x", UNRELATED, OTHER), r]), r)

    def test_match_via_status_image_digest(self):
        r = rev("a", UNRELATED, SHA, status_digest=PLAT)
        self.assertIs(m.matching_revision(SHA, IDX, INDEX, [r]), r)

    def test_match_via_index_digest(self):
        r = rev("a", IDX, SHA)
        self.assertIs(m.matching_revision(SHA, IDX, INDEX, [r]), r)

    def test_single_manifest_only_tag_digest(self):
        self.assertIsNotNone(m.matching_revision(SHA, IDX, SINGLE, [rev("a", IDX, SHA)]))
        self.assertIsNone(m.matching_revision(SHA, IDX, SINGLE, [rev("a", PLAT, SHA)]))

    def test_git_sha_mismatch_rejects(self):
        self.assertIsNone(m.matching_revision(SHA, IDX, INDEX, [rev("a", PLAT, OTHER), rev("b", IDX, OTHER)]))

    def test_no_env_rejects(self):
        r = rev("a", PLAT, SHA)
        r["spec"]["containers"][0]["env"] = []
        self.assertIsNone(m.matching_revision(SHA, IDX, INDEX, [r]))

    def test_no_digest_match_rejects(self):
        self.assertIsNone(m.matching_revision(SHA, IDX, INDEX, [rev("a", UNRELATED, SHA)]))

    def test_empty_revisions_rejects(self):
        self.assertIsNone(m.matching_revision(SHA, IDX, INDEX, []))


class Cli(unittest.TestCase):
    def run_cli(self, revisions):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "i.json").write_text(json.dumps(INDEX))
            (Path(d) / "r.json").write_text(json.dumps(revisions))
            return subprocess.run(
                [sys.executable, str(Path(m.__file__)), "--sha", SHA, "--digest", IDX, "--index", f"{d}/i.json", "--revisions", f"{d}/r.json"],
                capture_output=True, text=True,
            )

    def test_exit_codes(self):
        ok = self.run_cli([rev("rev-1", PLAT, SHA)])
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "rev-1"))
        self.assertEqual(self.run_cli([rev("rev-1", PLAT, OTHER)]).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
