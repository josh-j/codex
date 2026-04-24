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
        for name in ("vsphere", "datacenter", "vcsa")
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


def _dc_node(tree: ReportNode) -> ReportNode:
    # vsphere → vc → dc
    return tree.children[0].children[0]


def _esxi_leaf(tree: ReportNode) -> ReportNode:
    return _dc_node(tree).children[0]


class TestBuildTreeNodeView:
    def test_datacenter_node_renders_compute_sections(self, schemas, synthetic_vsphere_tree):
        dc = _dc_node(synthetic_vsphere_tree)
        view = build_tree_node_view(dc, schema=schemas["datacenter"], ctx=ReportContext(report_stamp="20260421"))
        widget_names = [w.get("name") for w in view["widgets"]]
        assert "Compute — Clusters" in widget_names
        assert "Storage — Datastores" in widget_names

    def test_breadcrumbs_walk_ancestors(self, schemas, synthetic_vsphere_tree):
        dc = _dc_node(synthetic_vsphere_tree)
        view = build_tree_node_view(dc, schema=schemas["datacenter"])
        crumbs = [c["text"] for c in view["nav"]["breadcrumbs"]]
        # Site → vSphere → vc-prod-01 → DC-East
        assert crumbs[0] == "Site"
        assert crumbs[1] == "vSphere"
        assert crumbs[-1] == "DC-East"

    def test_descendant_rollup_surfaces_child_alert_counts(self, schemas, synthetic_vsphere_tree, esxi_schema):
        """Root's children block carries each child's descendant alert counts."""
        from ncs_reporter.view_models.tree_render import _compute_tree_state

        all_schemas = {**schemas, "esxi": esxi_schema}
        state = _compute_tree_state(synthetic_vsphere_tree, all_schemas)

        root_entry = state[id(synthetic_vsphere_tree)]
        assert set(root_entry) == {"fields", "alerts", "rollup"}
        assert set(root_entry["rollup"].keys()) == {"critical", "warning", "info"}
        for child in synthetic_vsphere_tree.children:
            assert id(child) in state

    def test_children_block_populated(self, schemas, synthetic_vsphere_tree):
        # vSphere root directly lists its vCenter children.
        view = build_tree_node_view(synthetic_vsphere_tree, schema=schemas["vsphere"])
        assert len(view["nav"]["children"]) == 1  # one vCenter


class TestRenderTree:
    def test_writes_one_html_per_node(self, tmp_path: Path, schemas, esxi_schema, synthetic_vsphere_tree):
        env = get_jinja_env()
        # Map the vcsa schema name to the simpler vsphere schema so the
        # synthetic bundle (which omits alarm_count / backup_schedules /
        # etc.) still renders cleanly — the real vcsa.yaml expects that
        # richer shape and isn't under test here.
        all_schemas = {**schemas, "vcsa": schemas["vsphere"], "esxi": esxi_schema}
        written = render_tree(
            synthetic_vsphere_tree,
            schemas_by_name=all_schemas,
            env=env,
            output_root=tmp_path,
            ctx=ReportContext(report_stamp="20260421"),
        )
        # vsphere + vcenter + dc + 2 esxi = 5
        assert len(written) >= 5
        vsphere_html = tmp_path / "vsphere" / "vsphere.html"
        assert vsphere_html.exists()
        content = vsphere_html.read_text()
        assert "vSphere" in content
        assert "breadcrumb-current" in content

        dc_html = tmp_path / "vsphere" / "vc-prod-01" / "dc-east" / "dc-east.html"
        assert dc_html.exists()
        dc_content = dc_html.read_text()
        assert "DC-East" in dc_content

    def test_flat_inventory_tree_round_trip(self, tmp_path: Path, esxi_schema):
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
        # vCenter page at platform/vsphere/vc-prod-01/vc-prod-01.html;
        # DC at platform/vsphere/vc-prod-01/dc-east/dc-east.html → relative: dc-east/dc-east.html
        assert child_urls == ["dc-east/dc-east.html"]

    def test_ancestor_link_ascends(self, schemas, synthetic_vsphere_tree):
        dc = _dc_node(synthetic_vsphere_tree)
        view = build_tree_node_view(dc, schema=schemas["datacenter"])
        # Breadcrumbs: [Site, vSphere, vc-prod-01, DC-East].
        # vSphere ascends two levels inside the vsphere subtree (dc → vc → vsphere).
        vsphere_crumb = view["nav"]["breadcrumbs"][1]
        assert vsphere_crumb["href"].endswith("vsphere.html")
        assert vsphere_crumb["href"].count("..") == 2

        site_crumb = view["nav"]["breadcrumbs"][0]
        # DC dir is 3 segments deep (vsphere/vc/dc); site.html is at the report root.
        assert site_crumb["href"] == "../../../site.html"
