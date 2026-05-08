from __future__ import annotations

from pathlib import Path

import yaml


def test_task_catalog_shape_is_valid() -> None:
    catalog_path = Path(__file__).resolve().parents[2] / "vars" / "task_catalog.yml"
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog = data["vmware_task_catalog"]

    assert set(catalog) == {entry["id"] for entry in catalog.values()}
    assert len(catalog) == len(set(catalog))

    for task_id, entry in catalog.items():
        assert entry["id"] == task_id
        assert entry["tier"] in (1, 2)
        assert entry["target_type"] in {"esxi", "vcsa", "vm"}
        assert isinstance(entry["read_only"], bool)
        assert isinstance(entry["inputs"], list)
        assert entry["target_selector"]
        assert entry["emits_operation_event"] is True
        assert "executor" in entry
        if entry["tier"] == 1:
            assert entry["read_only"] is True
        if entry["tier"] == 2:
            assert entry["read_only"] is False

