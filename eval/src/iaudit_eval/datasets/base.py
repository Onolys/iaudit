"""Dataset plug-in contract: Item, Adapter protocol, metadata, Dataset."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
ALL_SPLIT = "all"


class DatasetError(Exception):
    """Bad dataset folder, metadata, adapter, split or item."""


class Unmapped(Exception):
    """Adapter.project() could not map a response to the gold label space."""


@dataclass(frozen=True)
class Item:
    id: str  # unique in dataset; [A-Za-z0-9._-]{1,128}; used as a filename
    doc_id: str  # cluster key (source document)
    split: str
    payload: Mapping  # adapter-private; JSON-serialisable
    meta: Mapping  # slice attributes; JSON-serialisable


class Adapter(Protocol):
    """Required methods. Optional hooks (post_download, download, pairs, item_row,
    mapping_version, report_extra) are looked up with getattr by their callers."""

    def items(self, split: str) -> Iterable[Item]: ...

    def to_request(self, item: Item) -> dict: ...

    def gold(self, item: Item) -> Any: ...

    def project(self, response: dict, item: Item) -> Any: ...


_KNOWN = (
    "name", "title", "description", "dataset_version", "kind", "splits", "default_split",
    "cluster_key", "license", "data_required", "sources", "test_split_note", "slices",
    "mapping", "references", "levels", "metrics", "pool_all", "gold_kind",
)  # fmt: skip


@dataclass(frozen=True)
class DatasetMeta:
    name: str
    title: str = ""
    description: str = ""
    dataset_version: str = ""
    kind: str = "adapter"
    splits: tuple[dict, ...] = ()
    default_split: str = ""
    cluster_key: str = ""
    license: dict = field(default_factory=dict)
    data_required: bool = False
    sources: tuple[dict, ...] = ()
    test_split_note: str | None = None
    slices: tuple[str, ...] = ()
    mapping: str | None = None
    references: str | None = None
    levels: dict = field(default_factory=dict)
    metrics: tuple[dict, ...] | None = None
    pool_all: bool = True
    gold_kind: str | None = None
    extra: dict = field(default_factory=dict)  # unknown keys, preserved verbatim

    @classmethod
    def from_dict(cls, raw: Mapping) -> DatasetMeta:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise DatasetError("metadata.json must be an object with a string 'name'")
        known = {k: raw[k] for k in _KNOWN if k in raw}
        for k in ("splits", "sources", "slices"):
            if k in known:
                known[k] = tuple(known[k])
        if known.get("metrics") is not None:
            known["metrics"] = tuple(known["metrics"])
        extra = {k: v for k, v in raw.items() if k not in _KNOWN}
        return cls(**known, extra=extra)

    def get(self, key: str, default: Any = None) -> Any:
        """Read a known or unknown metadata key."""
        if key in _KNOWN:
            return getattr(self, key)
        return self.extra.get(key, default)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        for k in _KNOWN:
            v = getattr(self, k)
            out[k] = list(v) if isinstance(v, tuple) else v
        out.update(self.extra)
        return out

    def split_names(self) -> list[str]:
        return [s["name"] for s in self.splits]


def validate_items(items: Iterable[Item]) -> list[Item]:
    """Preflight: ids are unique and filename-safe. Returns the items as a list."""
    out = list(items)
    seen: set[str] = set()
    for it in out:
        if not isinstance(it.id, str) or not ID_RE.fullmatch(it.id):
            raise DatasetError(f"invalid item id {it.id!r}: must match [A-Za-z0-9._-]{{1,128}}")
        if it.id in seen:
            raise DatasetError(f"duplicate item id {it.id!r}")
        seen.add(it.id)
    return out


@dataclass
class Dataset:
    meta: DatasetMeta
    adapter: Adapter

    def _split_items(self, split: str) -> list[Item]:
        return validate_items(self.adapter.items(split))

    def items(self, split: str) -> list[Item]:
        """Items of a declared split; "all" is the union, de-duplicated by id (first wins)."""
        names = self.meta.split_names()
        if split == ALL_SPLIT:
            seen: set[str] = set()
            out: list[Item] = []
            for name in names:
                for it in self._split_items(name):
                    if it.id not in seen:
                        seen.add(it.id)
                        out.append(it)
            return out
        if split not in names:
            raise DatasetError(f"unknown split {split!r}; declared: {names} (plus 'all')")
        return self._split_items(split)

    def split_sizes(self) -> dict[str, int]:
        sizes = {n: len(self._split_items(n)) for n in self.meta.split_names()}
        sizes[ALL_SPLIT] = len(self.items(ALL_SPLIT))
        return sizes
