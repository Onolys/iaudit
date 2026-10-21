"""Discover datasets under eval/datasets/*/metadata.json and load their adapters."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import sys
from pathlib import Path

from iaudit_eval import paths
from iaudit_eval.datasets.base import Dataset, DatasetError, DatasetMeta

_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _read_meta(folder: Path) -> DatasetMeta:
    try:
        raw = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DatasetError(f"cannot read {folder / 'metadata.json'}: {e}") from e
    meta = DatasetMeta.from_dict(raw)
    if meta.name != folder.name:
        raise DatasetError(f"metadata name {meta.name!r} != folder name {folder.name!r}")
    return meta


def list_datasets(root: Path | None = None) -> list[DatasetMeta]:
    root = Path(root) if root is not None else paths.datasets_dir()
    if not root.is_dir():
        return []
    return [
        _read_meta(d)
        for d in sorted(root.iterdir())
        if d.is_dir() and (d / "metadata.json").is_file()
    ]


def _load_adapter(folder: Path, data_dir: Path):
    path = folder / "adapter.py"
    if not path.is_file():
        raise DatasetError(f"missing adapter.py in {folder}")
    package = f"iaudit_eval_dataset_{folder.name.replace('-', '_')}"
    location = str(folder.resolve())
    parent = sys.modules.get(package)
    if parent is None or list(getattr(parent, "__path__", [])) != [location]:
        # The same dataset name may be loaded from separate plugin roots.
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]
        package_spec = importlib.machinery.ModuleSpec(package, loader=None, is_package=True)
        package_spec.submodule_search_locations = [location]
        sys.modules[package] = importlib.util.module_from_spec(package_spec)
    modname = f"{package}.adapter"
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise DatasetError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(modname, None)
        raise DatasetError(f"error importing {path}: {e}") from e
    create = getattr(module, "create", None)
    if not callable(create):
        raise DatasetError(f"{path} must define create(data_dir) -> Adapter")
    return create(data_dir)


def load(name: str, root: Path | None = None, data_root: Path | None = None) -> Dataset:
    if not _NAME_RE.fullmatch(name):
        raise DatasetError(f"invalid dataset name {name!r}")
    root = Path(root) if root is not None else paths.datasets_dir()
    folder = root / name
    if not (folder / "metadata.json").is_file():
        raise DatasetError(f"unknown dataset {name!r}")
    meta = _read_meta(folder)
    data_root = Path(data_root) if data_root is not None else paths.data_dir()
    return Dataset(meta=meta, adapter=_load_adapter(folder, data_root / name))
