"""Guard for tasks that write blobs: no audio or artifact may outlive a session delete.

`DELETE` marks the session `deleting` first and sweeps the blobs afterwards. A task calls
`ensure_alive` right after its writes: a write before the mark is swept by the delete, and one
after it is removed here (the task then answers `gone`), so nothing survives either order.
"""

from onolys_api.repo.base import NotFoundError, Repo
from onolys_api.storage.base import BlobStore


def ensure_alive(repo: Repo, blobs: BlobStore, uid: str, sid: str) -> None:
    """Raise NotFoundError (and purge every session prefix) if the session is gone or deleting."""
    try:
        if repo.get_session(uid, sid).state != "deleting":
            return
    except NotFoundError:
        pass
    blobs.delete_prefix(f"{uid}/{sid}/")
    blobs.delete_prefix(f"uploads/{uid}/{sid}/")
    raise NotFoundError()
