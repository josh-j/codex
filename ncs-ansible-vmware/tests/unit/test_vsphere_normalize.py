from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "module_utils"))

from vsphere.normalize import normalize_events, normalize_inventory


def test_normalize_inventory_builds_graph_counts_and_relationships() -> None:
    graph = normalize_inventory(
        vcenter="vcsa.lab",
        datacenters=[{"name": "dc-a"}],
        clusters=[{"name": "cluster-a", "datacenter": "dc-a", "hosts": [{"name": "esxi-01"}]}],
        hosts=[{"name": "esxi-01", "datacenter": "dc-a", "cluster": "cluster-a"}],
        vms=[{"guest_name": "app-01", "esxi_hostname": "esxi-01", "power_state": "poweredOn"}],
        datastores=[{"name": "ds-01", "capacity": 1024, "freeSpace": 512}],
        networks=[{"name": "VM Network"}],
        tags=[{"name": "Owner:Platform"}],
        snapshots=[{"vm_name": "app-01", "name": "pre-stig"}],
    )

    assert graph["schema_version"] == 1
    assert graph["kind"] == "vsphere_graph"
    assert graph["metadata"]["counts"] == {
        "datacenters": 1,
        "clusters": 1,
        "hosts": 1,
        "vms": 1,
        "datastores": 1,
        "networks": 1,
        "tags": 1,
        "snapshots": 1,
        "alarms": 0,
    }
    assert graph["clusters"][0]["host_ids"] == [graph["hosts"][0]["id"]]
    assert graph["vms"][0]["host_id"] == graph["hosts"][0]["id"]
    assert graph["snapshots"][0]["vm_id"] == graph["vms"][0]["id"]


def test_normalize_events_caps_rows_and_preserves_window() -> None:
    events = normalize_events(
        vcenter="vcsa.lab",
        alarms=[{"key": "alarm-1", "message": "Host memory", "severity": "critical"}],
        tasks=[{"key": "task-1", "message": "Reconfigure VM"}],
        events=[{"key": f"event-{i}", "message": f"Event {i}"} for i in range(3)],
        window_hours=12,
        limit=2,
    )

    assert events["schema_version"] == 1
    assert events["window_hours"] == 12
    assert len(events["events"]) == 2
    assert events["active_alarms"][0]["kind"] == "alarm"
    assert events["tasks"][0]["kind"] == "task"

