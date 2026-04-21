"""End-to-end smoke test: ReportNode → rendered HTML tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from ncs_reporter._report_context import get_jinja_env
from ncs_reporter.models.node_path import NodePath
from ncs_reporter.models.tree import (
    ReportNode,
    build_flat_inventory_tree,
    build_vsphere_tree,
)
from ncs_reporter.schema_loader import load_schema_from_file
from ncs_reporter._report_context import ReportContext
from ncs_reporter.view_models.tree_render import (
    build_tree_node_view,
    render_tree,
)

from conftest import CONFIGS_DIR


@pytest.fixture
def schemas() -> dict:
    return {
        name: load_schema_from_file(CONFIGS_DIR / f"{name}.yaml")
        for name in ("vsphere", "datacenter", "cluster")
    }


@pytest.fixture
def esxi_schema():
    return load_schema_from_file(CONFIGS_DIR / "esxi.yaml")


@pytest.fixture
def synthetic_vsphere_tree() -> ReportNode:
    return build_vsphere_tree(
        vcenter_bundles={
            "vc-prod-01": {
                "appliance_version": "7.0.3",
                "clusters": {
                    "CL-A": {"name": "CL-A", "datacenter": "DC-East", "ha_enabled": True,
                             "drs_enabled": True, "host_count": 2, "cpu_usage_pct": 42.0,
                             "mem_usage_pct": 55.0},
                },
                "datastores": [{"name": "ds-A1", "datacenter": "DC-East",
                                "capacity_gb": 1000, "free_gb": 400, "used_pct": 60.0}],
                "dvswitches": [{"name": "dvs-east", "num_ports": 128, "num_uplinks": 4, "mtu": 9000}],
            },
        },
        esxi_bundles={
            "esxi-01.lab": {"cluster": "CL-A", "datacenter": "DC-East"},
            "esxi-02.lab": {"cluster": "CL-A", "datacenter": "DC-East"},
        },
        vm_bundles={
            "vc-prod-01": {
                "virtual_machines": [
                    {"guest_name": "web-01", "cluster": "CL-A", "esxi_host": "esxi-01.lab",
                     "power_state": "poweredOn", "owner_email": "a@x.y"},
                ],
            },
        },
    )


class TestBuildTreeNodeView:
    def test_cluster_node_evaluates_compute_fields(self, schemas, synthetic_vsphere_tree):
        cluster = synthetic_vsphere_tree.children[0].children[0].children[0]
        view = build_tree_node_view(cluster, schema=schemas["cluster"], ctx=ReportContext(report_stamp="20260421"))
        fields_via_widgets = {w.get("slug"): w for w in view["widgets"]}
        kpi = fields_via_widgets["cluster_kpis"]
        cards = {c["name"]: c["value"] for c in kpi["cards"]}
        assert str(cards["VMs"]) == "1"
        assert str(cards["Powered On"]) == "1"

    def test_datacenter_node_renders_compute_sections(self, schemas, synthetic_vsphere_tree):
        dc = synthetic_vsphere_tree.children[0].children[0]
        view = build_tree_node_view(dc, schema=schemas["datacenter"], ctx=ReportContext(report_stamp="20260421"))
        widget_names = [w.get("name") for w in view["widgets"]]
        assert "Compute — Clusters" in widget_names
        assert "Storage — Datastores" in widget_names

    def test_breadcrumbs_walk_ancestors(self, schemas, synthetic_vsphere_tree):
        cluster = synthetic_vsphere_tree.children[0].children[0].children[0]
        view = build_tree_node_view(cluster, schema=schemas["cluster"])
        crumbs = [c["text"] for c in view["nav"]["breadcrumbs"]]
        # vsphere → vc-prod-01 → DC-East → CL-A
        assert crumbs[0] == "vSphere"
        assert crumbs[-1] == "CL-A"

    def test_children_block_populated(self, schemas, synthetic_vsphere_tree):
        vc = synthetic_vsphere_tree.children[0]
        view = build_tree_node_view(vc, schema=schemas["vsphere"])  # using vsphere schema for smoke
        assert len(view["nav"]["children"]) == 1  # one datacenter


class TestRenderTree:
    def test_writes_one_html_per_node(self, tmp_path: Path, schemas, esxi_schema, synthetic_vsphere_tree):
        env = get_jinja_env()
        all_schemas = {**schemas, "vcsa": schemas["vsphere"], "esxi": esxi_schema}
        written = render_tree(
            synthetic_vsphere_tree,
            schemas_by_name=all_schemas,
            env=env,
            output_root=tmp_path,
            ctx=ReportContext(report_stamp="20260421"),
        )
        assert len(written) >= 5  # vsphere + vcenter + dc + cluster + 2 esxi
        vsphere_html = tmp_path / "vsphere" / "vsphere.html"
        assert vsphere_html.exists()
        content = vsphere_html.read_text()
        assert "vSphere" in content
        assert "breadcrumb-current" in content
        assert 'id="tree-children"' in content or "no children" in content.lower() or "vc-prod-01" in content

        cluster_html = tmp_path / "vsphere" / "vc-prod-01" / "dc-east" / "cl-a" / "cl-a.html"
        assert cluster_html.exists()
        cluster_content = cluster_html.read_text()
        assert "CL-A" in cluster_content

    def test_flat_inventory_tree_round_trip(self, tmp_path: Path, esxi_schema):
        # Flat inventory using a simple schema — render the inventory root + two child nodes.
        root = build_flat_inventory_tree(
            inventory_slug="esxi-standalone",
            title="ESXi (Standalone Smoke)",
            schema_name="esxi",
            host_bundles={"host-01": {"cluster": "", "datacenter": ""},
                          "host-02": {"cluster": "", "datacenter": ""}},
            host_schema_name="esxi",
        )
        env = get_jinja_env()
        inventory_root_schema = load_schema_from_file(CONFIGS_DIR / "inventory_root.yaml")
        written = render_tree(
            root,
            schemas_by_name={"esxi": esxi_schema, "inventory_root": inventory_root_schema},
            env=env,
            output_root=tmp_path,
            ctx=ReportContext(report_stamp="20260421"),
        )
        assert len(written) == 3  # root + 2 hosts
        assert (tmp_path / "esxi-standalone" / "esxi-standalone.html").exists()
        assert (tmp_path / "esxi-standalone" / "host-01" / "host-01.html").exists()


class TestRelativeLinks:
    def test_child_link_is_relative_not_absolute(self, schemas, synthetic_vsphere_tree):
        vc = synthetic_vsphere_tree.children[0]
        view = build_tree_node_view(vc, schema=schemas["vsphere"])
        child_urls = [c["url"] for c in view["nav"]["children"]]
        # vCenter page is at vsphere/vc-prod-01/vc-prod-01.html; DC is at
        # vsphere/vc-prod-01/dc-east/dc-east.html → relative URL: dc-east/dc-east.html
        assert child_urls == ["dc-east/dc-east.html"]

    def test_ancestor_link_ascends(self, schemas, synthetic_vsphere_tree):
        cluster = synthetic_vsphere_tree.children[0].children[0].children[0]
        view = build_tree_node_view(cluster, schema=schemas["cluster"])
        # Cluster at vsphere/vc-prod-01/dc-east/cl-a/cl-a.html — vSphere root link
        # should ascend three levels.
        root_crumb = view["nav"]["breadcrumbs"][0]
        # Cluster dir has depth 4; vSphere root is depth 1 → 3 levels up to its dir,
        # then up 1 more to reach the dir's parent → wrong. Correct: from cluster's
        # dir, vsphere.html lives at ../../../vsphere.html (3 "../" + "vsphere.html").
        # But our helper puts the file NAME only after the up-traversal, since both
        # share the vsphere prefix (common=1). Let's just check it's a relative path.
        assert root_crumb["href"].endswith("vsphere.html")
        assert root_crumb["href"].count("..") == 3
