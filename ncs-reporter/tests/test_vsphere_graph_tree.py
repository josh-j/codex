from __future__ import annotations

from pathlib import Path

import yaml

from ncs_reporter.models.tree import build_tree_from_folders
from ncs_reporter.schema_loader import discover_schemas
from ncs_reporter.view_models.tree_render import _compute_tree_state


def test_vsphere_graph_materializes_projection_tree(tmp_path: Path) -> None:
    graph = {
        "kind": "vsphere_graph",
        "schema_version": 1,
        "vcenters": [{"name": "vcsa-01", "hostname": "vcsa-01"}],
        "datacenters": [{"name": "dc-a"}],
        "clusters": [{"name": "cluster-a", "datacenter": "dc-a", "host_ids": ["host:vcsa-01:esxi-01"], "ha_enabled": True, "drs_enabled": True}],
        "hosts": [{"name": "esxi-01", "datacenter": "dc-a", "cluster": "cluster-a", "connection_state": "connected"}],
        "vms": [{"name": "app-01", "host": "esxi-01", "cluster": "cluster-a", "power_state": "poweredOn"}],
        "datastores": [],
        "networks": [],
        "tags": [],
        "snapshots": [],
        "alarms": [],
        "metadata": {"counts": {"datacenters": 1, "clusters": 1, "hosts": 1, "vms": 1, "datastores": 0, "networks": 0, "tags": 0, "snapshots": 0, "alarms": 0}},
    }
    raw_dir = tmp_path / "vsphere" / "vcsa-01"
    raw_dir.mkdir(parents=True)
    (raw_dir / "inventory.yaml").write_text(
        yaml.safe_dump({"metadata": {"host": "vcsa-01"}, "data": graph}),
        encoding="utf-8",
    )

    tree = build_tree_from_folders(
        "vsphere",
        root_title="vSphere",
        root_schema="vsphere",
        bundles_root=tmp_path,
    )

    assert tree is not None
    tiers = [(node.tier, node.title) for node in tree.walk()]
    assert tiers == [
        ("inventory", "vSphere"),
        ("vcenter", "vcsa-01"),
        ("datacenter", "dc-a"),
        ("cluster", "cluster-a"),
        ("esxi_host", "esxi-01"),
        ("vm", "app-01"),
    ]
    vm_node = list(tree.walk())[-1]
    assert vm_node.data_source({})["raw_vm"]["data"]["virtual_machines"][0]["name"] == "app-01"


def test_vm_child_alerts_roll_up_to_esxi_parent(tmp_path: Path) -> None:
    graph = {
        "kind": "vsphere_graph",
        "schema_version": 1,
        "vcenters": [{"name": "vcsa-01", "hostname": "vcsa-01"}],
        "datacenters": [{"name": "dc-a"}],
        "clusters": [{"name": "cluster-a", "datacenter": "dc-a", "host_ids": ["host:vcsa-01:esxi-01"]}],
        "hosts": [{"name": "esxi-01", "datacenter": "dc-a", "cluster": "cluster-a", "connection_state": "connected"}],
        "vms": [
            {
                "name": "app-01",
                "guest_name": "app-01",
                "host": "esxi-01",
                "esxi_hostname": "esxi-01",
                "cluster": "cluster-a",
                "datacenter": "dc-a",
                "power_state": "poweredOff",
                "tools_status": "toolsNotRunning",
                "tags": [],
                "attributes": {},
            }
        ],
        "datastores": [],
        "networks": [],
        "tags": [],
        "snapshots": [],
        "alarms": [],
        "metadata": {"counts": {"datacenters": 1, "clusters": 1, "hosts": 1, "vms": 1}},
    }
    raw_dir = tmp_path / "vsphere" / "vcsa-01"
    raw_dir.mkdir(parents=True)
    (raw_dir / "inventory.yaml").write_text(
        yaml.safe_dump({"metadata": {"host": "vcsa-01"}, "data": graph}),
        encoding="utf-8",
    )

    tree = build_tree_from_folders("vsphere", root_title="vSphere", root_schema="vsphere", bundles_root=tmp_path)
    assert tree is not None
    nodes = list(tree.walk())
    esxi_node = next(node for node in nodes if node.tier == "esxi_host")
    vm_node = next(node for node in nodes if node.tier == "vm")

    discover_schemas.cache_clear()
    schemas = discover_schemas()
    state = _compute_tree_state(tree, schemas)

    assert {alert["id"] for alert in state[id(vm_node)]["alerts"]} >= {"powered_off_vms"}
    assert "powered_off_vms" not in {alert["id"] for alert in state[id(esxi_node)]["alerts"]}
    assert state[id(esxi_node)]["rollup"]["warning"] >= 1
    assert any(
        alert["id"] == "powered_off_vms" and alert["origin"] == "app-01"
        for alert in state[id(esxi_node)]["descendant_alerts"]
    )
