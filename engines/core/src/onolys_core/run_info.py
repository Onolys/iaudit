"""Generic run-provenance helpers. No prompt or engine knowledge lives here."""

import hashlib
from collections.abc import Iterable
from pathlib import Path


def hash_files(paths: Iterable[Path], length: int = 16) -> str:
    """Truncated sha256 over the concatenated bytes of `paths`, in the order given."""
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:length]
