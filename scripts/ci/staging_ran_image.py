#!/usr/bin/env python3
"""deploy-prod `resolve`: did a staging Cloud Run revision run this image at this commit?

The Artifact Registry `:<sha>` tag points at an OCI index / manifest list (tag digest). Cloud Run resolves that to the
platform manifest digest and stores THAT in the revision (spec image and status.imageDigest). So a revision counts when
its image digest equals the tag digest OR one of the index's platform manifest digests, AND its env GIT_SHA == sha.

Usage: staging_ran_image.py --sha SHA --digest sha256:... --index INDEX.json --revisions REVISIONS.json
  INDEX.json      manifest fetched from the registry (index/list, or a single manifest -> only the tag digest counts)
  REVISIONS.json  `gcloud run revisions list --format=json` (or any JSON list of Cloud Run v1 revisions)
Exit 0 = match (prints the matching revision), 1 = no match.
"""
import argparse
import json
import sys


def candidates(tag_digest, index):
    out = {tag_digest}
    for m in (index or {}).get("manifests") or []:
        if m.get("digest"):
            out.add(m["digest"])
    return out


def _digest_of(image):
    return image.split("@", 1)[1] if image and "@" in image else None


def revision_digests(rev):
    c = ((rev.get("spec") or {}).get("containers") or [{}])[0]
    found = {_digest_of(c.get("image"))}
    sd = (rev.get("status") or {}).get("imageDigest")
    if sd:
        found.add(_digest_of(sd) or sd)
    found.discard(None)
    return found


def revision_git_sha(rev):
    c = ((rev.get("spec") or {}).get("containers") or [{}])[0]
    for e in c.get("env") or []:
        if e.get("name") == "GIT_SHA":
            return e.get("value")
    return None


def matching_revision(sha, tag_digest, index, revisions):
    cands = candidates(tag_digest, index)
    for rev in revisions:
        if revision_git_sha(rev) == sha and revision_digests(rev) & cands:
            return rev
    return None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--digest", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--revisions", required=True)
    a = p.parse_args(argv)
    with open(a.index) as f:
        index = json.load(f)
    with open(a.revisions) as f:
        revisions = json.load(f)
    rev = matching_revision(a.sha, a.digest, index, revisions)
    if rev is None:
        return 1
    print((rev.get("metadata") or {}).get("name", "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
