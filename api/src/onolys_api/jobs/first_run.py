"""First-run gate hook (PRD R4). Stub until Task 11 adds the transactional `maybe_start_first_run`.

Called after each of the three inputs lands (transcript ready, speaker confirmed, rating
submitted); the transcribe worker calls it once the transcript is stored.
"""

from onolys_api.jobs.queue import TaskQueue
from onolys_api.repo.base import Repo


def maybe_start_first_run(repo: Repo, queue: TaskQueue, uid: str, sid: str) -> None:
    """No-op until Task 11."""
    return None
