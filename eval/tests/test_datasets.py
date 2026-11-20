import json
from pathlib import Path

import pytest

from iaudit_eval.datasets import Dataset, Item, Unmapped, list_datasets, load
from iaudit_eval.datasets.base import DatasetError, DatasetMeta, validate_items
from iaudit_eval.selection import select

ADAPTER = """
from iaudit_eval.datasets import Item

class A:
    def __init__(self, data_dir):
        self.data_dir = data_dir
    def items(self, split):
        ids = {"a": ["a1", "a2", "shared"], "b": ["b1", "shared", "b3"]}[split]
        return [Item(id=i, doc_id="d" + i[0], split=split, payload={}, meta={}) for i in ids]
    def to_request(self, item):
        return {}
    def gold(self, item):
        return 1
    def project(self, response, item):
        return 1

def create(data_dir):
    return A(data_dir)
"""


def make(root: Path, name="toy", adapter=ADAPTER, *, product="eaudit", **extra):
    d = root / product / name
    d.mkdir(parents=True)
    meta = {
        "name": name,
        "product": product,
        "title": "Toy",
        "description": "x",
        "dataset_version": "1",
        "kind": "adapter",
        "splits": [{"name": "a", "description": ""}, {"name": "b", "description": ""}],
        "default_split": "a",
        "cluster_key": "doc",
        "data_required": False,
        "license": {"name": "MIT", "redistributable": True, "contains_licensed_text": False},
        "sources": [],
        "slices": [],
    }
    meta.update(extra)
    (d / "metadata.json").write_text(json.dumps(meta))
    (d / "adapter.py").write_text(adapter)
    return d


def items(n, doc="d"):
    return [Item(id=f"i{k:03d}", doc_id=doc, split="a", payload={}, meta={}) for k in range(n)]


def test_discovery_and_load(tmp_path):
    make(tmp_path)
    make(tmp_path, name="other", product="paudit")
    (tmp_path / "junk").mkdir()  # no metadata.json: ignored
    assert [m.name for m in list_datasets(tmp_path)] == ["other", "toy"]
    ds = load("toy", root=tmp_path, data_root=tmp_path / "data")
    assert isinstance(ds, Dataset)
    assert ds.meta.default_split == "a"
    assert ds.adapter.data_dir == tmp_path / "data" / "toy"
    assert ds.meta.pool_all is True


def test_unknown_keys_preserved(tmp_path):
    make(tmp_path, adapter_version="3", item_unit="sentence")
    m = list_datasets(tmp_path)[0]
    assert m.extra == {"adapter_version": "3", "item_unit": "sentence"}
    assert m.get("item_unit") == "sentence"
    assert m.to_dict()["adapter_version"] == "3"


def test_name_must_match_folder(tmp_path):
    d = make(tmp_path)
    m = json.loads((d / "metadata.json").read_text())
    m["name"] = "nope"
    (d / "metadata.json").write_text(json.dumps(m))
    with pytest.raises(DatasetError):
        list_datasets(tmp_path)


def test_load_unknown(tmp_path):
    with pytest.raises(DatasetError):
        load("missing", root=tmp_path)


def test_adapter_module_namespaced(tmp_path):
    make(tmp_path)
    load("toy", root=tmp_path)
    import sys

    assert any(k.startswith("iaudit_eval_dataset_toy") for k in sys.modules)


def test_split_all_union_dedup_and_sizes(tmp_path):
    make(tmp_path)
    ds = load("toy", root=tmp_path)
    assert [i.id for i in ds.items("all")] == ["a1", "a2", "shared", "b1", "b3"]
    assert ds.split_sizes() == {"a": 3, "b": 3, "all": 5}
    with pytest.raises(DatasetError):
        ds.items("zzz")


@pytest.mark.parametrize("bad", ["", "a/b", "a b", "ü", "x" * 129, "../x"])
def test_bad_ids_rejected(bad):
    with pytest.raises(DatasetError):
        validate_items([Item(id=bad, doc_id="d", split="a", payload={}, meta={})])


def test_duplicate_ids_rejected():
    it = items(2)
    with pytest.raises(DatasetError):
        validate_items([it[0], it[0]])


def test_dataset_items_validates(tmp_path):
    bad = ADAPTER.replace('"a1"', '"a/1"')
    make(tmp_path, adapter=bad)
    with pytest.raises(DatasetError):
        load("toy", root=tmp_path).items("a")


def test_missing_create(tmp_path):
    make(tmp_path, adapter="x = 1\n")
    with pytest.raises(DatasetError):
        load("toy", root=tmp_path)


def test_unmapped_is_exception():
    assert issubclass(Unmapped, Exception)


def test_select_deterministic_and_seeded():
    its = items(20)
    a = select(its, 3, 0)
    assert a == select(list(reversed(its)), 3, 0)
    assert len(a) == 3
    assert [i.id for i in a] == sorted(i.id for i in a)
    assert [i.id for i in a] != [i.id for i in select(its, 3, 1)]


def test_select_all():
    its = items(5)
    assert select(its, None, 0) == its
    assert select(list(reversed(its)), 99, 0) == its
    assert select(its, 0, 0) == []


def test_multifile_adapter_relative_imports_and_same_name_different_roots(tmp_path):
    adapter = '''
from .helper import make_adapter

def create(data_dir):
    return make_adapter(data_dir)
'''
    for root_name, value in [("first", "first evidence"), ("second", "second evidence")]:
        root = tmp_path / root_name
        folder = make(root, name="multifile", adapter=adapter)
        (folder / "helper.py").write_text(
            "from types import SimpleNamespace\n"
            f"def make_adapter(data_dir): return SimpleNamespace(value={value!r})\n"
        )
    first = load("multifile", root=tmp_path / "first")
    again = load("multifile", root=tmp_path / "first")
    second = load("multifile", root=tmp_path / "second")
    assert first.adapter.value == again.adapter.value == "first evidence"
    assert second.adapter.value == "second evidence"
    assert load("multifile", root=tmp_path / "first").adapter.value == "first evidence"


@pytest.mark.parametrize("operation", [list_datasets, lambda root: load("toy", root=root)])
def test_duplicate_dataset_names_across_products_rejected(tmp_path, operation):
    make(tmp_path, product="eaudit")
    make(tmp_path, product="paudit")
    with pytest.raises(DatasetError, match="duplicate.*toy"):
        operation(tmp_path)


def test_flat_dataset_folder_is_not_discovered(tmp_path):
    make(tmp_path, product="legacy").rename(tmp_path / "toy")
    assert list_datasets(tmp_path) == []
    with pytest.raises(DatasetError, match="unknown"):
        load("toy", root=tmp_path)


def test_product_derived_from_parent_and_serialized(tmp_path):
    make(tmp_path, product="paudit")
    meta = list_datasets(tmp_path)[0]
    assert meta.product == "paudit"
    assert meta.get("product") == "paudit"
    assert meta.to_dict()["product"] == "paudit"
    assert "product" not in meta.extra
    assert load("toy", root=tmp_path).meta.product == "paudit"


@pytest.mark.parametrize("operation", [list_datasets, lambda root: load("toy", root=root)])
def test_product_must_match_parent(tmp_path, operation):
    folder = make(tmp_path)
    raw = json.loads((folder / "metadata.json").read_text())
    raw["product"] = "paudit"
    (folder / "metadata.json").write_text(json.dumps(raw))
    with pytest.raises(DatasetError, match="product.*paudit.*eaudit"):
        operation(tmp_path)


@pytest.mark.parametrize("raw", [{"name": "toy"}, {"name": "toy", "product": None}, {"name": "toy", "product": 3}])
def test_product_is_required_string(raw):
    with pytest.raises(DatasetError, match="product"):
        DatasetMeta.from_dict(raw)
