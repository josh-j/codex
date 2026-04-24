"""Tests for ReportNode + tree assembly."""

from __future__ import annotations

from ncs_reporter.models.node_path import NodePath
from ncs_reporter.models.tree import (
    ReportNode,
    build_flat_inventory_tree,
    build_vsphere_tree,
)


class TestReportNode:
    def test_root_has_no_parent_or_ancestors(self) -> None:
        root = ReportNode(
            tier="inventory",
            slug="vsphere",
            schema_name="vsphere",
            node_path=NodePath.product("vsphere"),
        )
        assert root.is_root
        assert root.ancestors() == []
        assert root.depth == 0

    def test_find_or_add_child_is_idempotent(self) -> None:
        root = ReportNode(
            tier="inventory",
            slug="vsphere",
            schema_name="vsphere",
            node_path=NodePath.product("vsphere"),
        )
        a = root.find_or_add_child("vc-01", tier="vcenter", schema_name="vcsa")
        b = root.find_or_add_child("vc-01", tier="vcenter", schema_name="vcsa")
        assert a is b
        assert len(root.children) == 1

    def test_walk_yields_preorder(self) -> None:
        root = ReportNode(
            tier="inventory",
            slug="vsphere",
            schema_name="vsphere",
            node_path=NodePath.product("vsphere"),
        )
        vc = root.find_or_add_child("vc-01", tier="vcenter", schema_name="vcsa")
        dc = vc.find_or_add_child("dc-east", tier="datacenter", schema_name="datacenter")
        dc.find_or_add_child("cluster-01", tier="cluster", schema_name="cluster")
        slugs = [n.slug for n in root.walk()]
        assert slugs == ["vsphere", "vc-01", "dc-east", "cluster-01"]

    def test_ancestors_returns_ordered_path(self) -> None:
        root = ReportNode(
            tier="inventory",
            slug="vsphere",
            schema_name="vsphere",
            node_path=NodePath.product("vsphere"),
        )
        vc = root.find_or_add_child("vc-01", tier="vcenter", schema_name="vcsa")
        dc = vc.find_or_add_child("dc-east", tier="datacenter", schema_name="datacenter")
        cluster = dc.find_or_add_child("cluster-01", tier="cluster", schema_name="cluster")
        assert [a.slug for a in cluster.ancestors()] == ["vsphere", "vc-01", "dc-east"]


class TestBuildVsphereTree:
    def test_assembles_full_hierarchy(self) -> None:
        vcenter_bundles = {
            "vc-prod-01": {
                "appliance_version": "7.0.3",
                "clusters": {
                    "Cluster-A": {"datacenter": "DC-East", "ha_enabled": True, "host_count": 2},
                    "Cluster-B": {"datacenter": "DC-East", "ha_enabled": False, "host_count": 1},
                    "Cluster-C": {"datacenter": "DC-West", "ha_enabled": True, "host_count": 1},
                },
                "datastores": [
                    {"name": "ds-A1", "datacenter": "DC-East"},
                    {"name": "ds-C1", "datacenter": "DC-West"},
                ],
                "dvswitches": [{"name": "dvs-east"}],
            },
        }
        esxi_bundles = {
            "esxi-01.lab": {"cluster": "Cluster-A", "datacenter": "DC-East"},
            "esxi-02.lab": {"cluster": "Cluster-A", "datacenter": "DC-East"},
            "esxi-03.lab": {"cluster": "Cluster-B", "datacenter": "DC-East"},
            "esxi-04.lab": {"cluster": "Cluster-C", "datacenter": "DC-West"},
        }
        vm_bundles = {
            "vc-prod-01": {
                "virtual_machines": [
                    {"guest_name": "web-01", "cluster": "Cluster-A", "esxi_host": "esxi-01.lab"},
                    {"guest_name": "web-02", "cluster": "Cluster-A", "esxi_host": "esxi-02.lab"},
                    {"guest_name": "db-01", "cluster": "Cluster-B", "esxi_host": "esxi-03.lab"},
                ],
            },
        }

        root = build_vsphere_tree(
            vcenter_bundles=vcenter_bundles,
            esxi_bundles=esxi_bundles,
            vm_bundles=vm_bundles,
        )

        # vsphere → vc → 2 datacenters → ESXi hosts (no vcsa fleet tier)
        assert root.slug == "vsphere"
        assert [c.slug for c in root.children] == ["vc-prod-01"]

        vc = root.children[0]
        assert [c.slug for c in vc.children] == ["dc-east", "dc-west"]

        dc_east = vc.children[0]
        assert [c.slug for c in dc_east.children] == ["esxi-01-lab", "esxi-02-lab", "esxi-03-lab"]

        # Each ESXi node's data is filtered to its own VMs
        esxi_01 = dc_east.children[0]
        esxi_bundle = esxi_01.data_source({})
        vms = esxi_bundle["raw_esxi"]["data"]["virtual_machines"]
        assert [v["guest_name"] for v in vms] == ["web-01"]

    def test_datacenter_surfaces_esxi_rows_with_cluster_column(self) -> None:
        root = build_vsphere_tree(
            vcenter_bundles={
                "vc-01": {
                    "clusters": {
                        "CL-A": {"datacenter": "DC1"},
                        "CL-B": {"datacenter": "DC1"},
                    },
                    "datastores": [],
                    "dvswitches": [],
                },
            },
            esxi_bundles={
                "esxi-01": {"cluster": "CL-A", "datacenter": "DC1"},
                "esxi-02": {"cluster": "CL-B", "datacenter": "DC1"},
            },
            vm_bundles={"vc-01": {"virtual_machines": []}},
        )
        dc_node = root.children[0].children[0]
        dc_data = dc_node.data_source({})
        assert [row["title"] for row in dc_data["esxi_hosts"]] == ["esxi-01", "esxi-02"]
        assert [row["cluster"] for row in dc_data["esxi_hosts"]] == ["CL-A", "CL-B"]
        assert dc_data["esxi_host_count"] == 2

    def test_node_paths_derive_from_tree_structure(self) -> None:
        root = build_vsphere_tree(
            vcenter_bundles={"vc-01": {"clusters": {"CL-A": {"datacenter": "DC1"}}, "datastores": [], "dvswitches": []}},
            esxi_bundles={"esxi-01": {"cluster": "CL-A", "datacenter": "DC1"}},
            vm_bundles={"vc-01": {"virtual_machines": []}},
        )
        esxi_node = root.children[0].children[0].children[0]
        assert esxi_node.node_path.html_path.as_posix() == "platform/vsphere/vc-01/dc1/esxi-01/esxi-01.html"


class TestBuildFlatInventoryTree:
    def test_each_host_becomes_a_child(self) -> None:
        root = build_flat_inventory_tree(
            inventory_slug="ubuntu",
            title="Ubuntu",
            schema_name="ubuntu_inventory",
            host_bundles={"web-01": {"k": 1}, "web-02": {"k": 2}},
            host_schema_name="ubuntu",
        )
        assert root.slug == "ubuntu"
        assert [c.slug for c in root.children] == ["web-01", "web-02"]
        assert root.children[0].node_path.html_path.as_posix() == "platform/ubuntu/web-01/web-01.html"
        assert root.children[0].data_source({}) == {"raw_ubuntu": {"data": {"k": 1}, "metadata": {"host": "web-01"}}}
