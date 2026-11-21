"""Integration smoke: Firestore read/write against the local emulator.

Runs in CI under `firebase emulators:exec`; skipped when FIRESTORE_EMULATOR_HOST is unset.
"""

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"),
        reason="FIRESTORE_EMULATOR_HOST not set (run under firebase emulators:exec)",
    ),
]


def test_firestore_roundtrip():
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    client = firestore.Client(project="demo-onolys", credentials=AnonymousCredentials())
    ref = client.collection("ci_smoke").document(uuid.uuid4().hex)
    ref.set({"hello": "world", "n": 1})
    snap = ref.get()
    assert snap.exists
    assert snap.to_dict() == {"hello": "world", "n": 1}
    ref.delete()
    assert not ref.get().exists
