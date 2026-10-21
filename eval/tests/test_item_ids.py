"""Dataset item IDs retain the same contract through persistence and API guards."""

from dataclasses import replace

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import Dataset, Item, load
from iaudit_eval.datasets.base import DatasetError, validate_items
from iaudit_eval.engine import Selection, start_run
from iaudit_eval.server.guards import ApiError, resolve_under, validate_item_id

VALID_IDS = ("_item", "-item", ".item", "item..1", ".", "..", "...", "x" * 128)
INVALID_IDS = ("", "../x", "x/y", "x\\y", "/absolute", "x" * 129, "a\n", "é")


@pytest.mark.parametrize("item_id", VALID_IDS)
def test_item_id_round_trip_and_api_membership(tmp_path, item_id):
    item = Item(item_id, "doc", "dev", {}, {})
    assert validate_items([item]) == [item]
    rid = store.create_run(tmp_path, {"dataset": "synthetic", "item_ids": [item_id]})
    record = {"item_id": item_id, "status": "ok"}
    store.write_item(tmp_path, rid, record)
    assert list(store.iter_items(tmp_path, rid)) == [record]
    assert store.compute_totals(tmp_path, rid)["missing"] == 0
    assert validate_item_id(item_id, {item_id}) == item_id
    path = resolve_under(store.run_dir(tmp_path, rid), "items", f"{item_id}.json")
    assert path.is_file()
    with pytest.raises(ApiError):
        validate_item_id(item_id, set())


@pytest.mark.parametrize("item_id", INVALID_IDS)
def test_invalid_ids_rejected_by_dataset_store_and_api(tmp_path, item_id):
    with pytest.raises(DatasetError):
        validate_items([Item(item_id, "doc", "dev", {}, {})])
    rid = store.create_run(tmp_path, {"dataset": "synthetic", "item_ids": []})
    with pytest.raises(ValueError):
        store.write_item(tmp_path, rid, {"item_id": item_id})
    with pytest.raises(ApiError):
        validate_item_id(item_id, {item_id})
    assert list(store.iter_items(tmp_path, rid)) == []


@pytest.mark.parametrize("value", ("_run", "-run", ".", "..", "run..1", "../run"))
def test_item_contract_does_not_relax_run_or_dataset_paths(tmp_path, value):
    with pytest.raises(ValueError):
        store.run_dir(tmp_path, value)
    with pytest.raises(ValueError):
        store.new_run_id(value)


async def test_synthetic_run_persists_every_permitted_id(tmp_path):
    synthetic = load("synthetic")
    renamed = dict(zip((it.id for it in synthetic.items("all")), VALID_IDS, strict=True))

    class RenamedAdapter:
        def items(self, split):
            return [replace(it, id=renamed[it.id]) for it in synthetic.adapter.items(split)]

        def __getattr__(self, name):
            return getattr(synthetic.adapter, name)

    backend = FakeBackend("ok")
    client = AuditClient("http://fake", transport=backend.transport())
    dataset = Dataset(synthetic.meta, RenamedAdapter())
    handle = start_run(dataset, Selection(split="all"), base_url="http://fake", client=client,
                       runs_root=tmp_path, on_finish=None)
    await handle.wait()
    run = store.load_run(tmp_path, handle.run_id)
    assert handle.state == "finished"
    assert backend.count == 8
    assert run["totals"]["ok"] == 8 and run["totals"]["missing"] == 0
    records = list(store.iter_items(tmp_path, handle.run_id))
    assert {record["item_id"] for record in records} == set(VALID_IDS)
    assert all(record["status"] == "ok" and record["response"] for record in records)
    for record in records:
        item_id = validate_item_id(record["item_id"], set(run["item_ids"]))
        assert resolve_under(store.run_dir(tmp_path, handle.run_id),
                             "items", f"{item_id}.json").is_file()
