"""Build the storage seams (Repo, BlobStore) from Settings."""

import os
from pathlib import Path

from onolys_api.config import LOCAL_ENVS, Settings
from onolys_api.repo.base import Repo
from onolys_api.storage.base import BlobStore
from onolys_api.storage.fake import FakeBlobStore


def build_blobs(settings: Settings) -> BlobStore:
    """Local/test: FakeBlobStore (dir from FAKE_BLOB_DIR, else a temp dir). Cloud: GCS."""
    if settings.env in LOCAL_ENVS and not settings.audio_bucket:
        root = os.environ.get("FAKE_BLOB_DIR")
        return FakeBlobStore(root=None if not root else Path(root))
    from google.cloud import storage

    from onolys_api.storage.gcs import GcsBlobStore

    client = storage.Client(project=settings.gcp_project or None)
    signer = os.environ.get("BLOB_SIGNER_EMAIL") or None  # IAM signBlob on Cloud Run
    return GcsBlobStore(client, settings.audio_bucket, signer_email=signer)


def build_repo(settings: Settings, blobs: BlobStore) -> Repo:
    """Firestore (emulator if FIRESTORE_EMULATOR_HOST is set) except plain local/test: FakeRepo."""
    if settings.env in LOCAL_ENVS and not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        from onolys_api.repo.fake import FakeRepo

        return FakeRepo(blobs)
    from onolys_api.repo.firestore import FirestoreRepo, make_firestore_client

    return FirestoreRepo(make_firestore_client(settings), blobs)
