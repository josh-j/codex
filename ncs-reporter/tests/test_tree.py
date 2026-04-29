"""Tests for ReportNode + tree assembly."""

from __future__ import annotations

from pathlib import Path

import yaml

from ncs_reporter.models.node_path import NodePath
from ncs_reporter.models.report_schema import TreeLevel, TreeSpec
from ncs_reporter.models.tree import (
    ReportNode,
    build_tree_from_spec,
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


def _vsphere_spec() -> TreeSpec:
    """Two-tier spec matching ``vsphere.yaml``: vCenter → ESXi host."""
    return TreeSpec(
        root_slug="vsphere",
        root_title="vSphere",
        levels=[
            TreeLevel(tier="vcenter", schema="vcsa", bundle_key="raw_vcsa"),
            TreeLevel(tier="esxi_host", schema="esxi", bundle_key="raw_esxi", parent_tier="vcenter"),
        ],
    )


def _write_raw(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"metadata": {"host": path.parent.name}, "data": data}))


class TestBuildTreeFromSpec:
    def test_assembles_two_tier_hierarchy(self, tmp_path: Path) -> None:
        _write_raw(tmp_path / "vsphere/vc-prod-01/raw.yaml", {"appliance_version": "7.0.3"})
        for host in ("esxi-01-lab", "esxi-02-lab", "esxi-03-lab"):
            _write_raw(tmp_path / "vsphere/vc-prod-01" / host / "raw.yaml",
                       {"cluster": "CL-A", "datacenter": "DC-East"})

        root = build_tree_from_spec(_vsphere_spec(), bundles_root=tmp_path)
        assert root is not None
        assert root.slug == "vsphere"
        assert [c.slug for c in root.children] == ["vc-prod-01"]

        vc = root.children[0]
        assert [c.slug for c in vc.children] == ["esxi-01-lab", "esxi-02-lab", "esxi-03-lab"]
        # Each ESXi node carries its own data bundle.
        esxi_01 = vc.children[0]
        esxi_bundle = esxi_01.data_source({})
        assert esxi_bundle["raw_esxi"]["data"]["cluster"] == "CL-A"

    def test_returns_none_when_product_dir_absent(self, tmp_path: Path) -> None:
        root = build_tree_from_spec(_vsphere_spec(), bundles_root=tmp_path)
        assert root is None

    def test_node_paths_derive_from_tree_structure(self, tmp_path: Path) -> None:
        _write_raw(tmp_path / "vsphere/vc-01/raw.yaml", {"clusters": []})
        _write_raw(tmp_path / "vsphere/vc-01/esxi-01/raw.yaml",
                   {"cluster": "CL-A", "datacenter": "DC1"})

        root = build_tree_from_spec(_vsphere_spec(), bundles_root=tmp_path)
        assert root is not None
        esxi_node = root.children[0].children[0]
        assert esxi_node.node_path.html_path.as_posix() == "vsphere/vc-01/esxi-01/esxi-01.html"


class TestFlatInventoryFromSpec:
    """Flat products use a single-level tree spec with ``root_schema:
    inventory_root`` so they share the generic builder."""

    def test_one_level_spec_emits_flat_hosts(self, tmp_path: Path) -> None:
        spec = TreeSpec(
            root_slug="ubuntu",
            root_title="Ubuntu",
            root_schema="inventory_root",
            levels=[TreeLevel(tier="host", schema="ubuntu", bundle_key="raw_ubuntu")],
        )
        for host in ("web-01", "web-02"):
            _write_raw(tmp_path / "ubuntu" / host / "raw.yaml", {"k": 1})
        root = build_tree_from_spec(spec, bundles_root=tmp_path)
        assert root is not None
        assert root.slug == "ubuntu"
        assert root.schema_name == "inventory_root"
        assert [c.slug for c in root.children] == ["web-01", "web-02"]
        assert root.children[0].node_path.html_path.as_posix() == "ubuntu/web-01/web-01.html"
        # Generic tier rollup populates root.data_source with the host list.
        agg = root.data_source({})
        assert agg["host_count"] == 2
        assert {h["name"] for h in agg["hosts"]} == {"web-01", "web-02"}
