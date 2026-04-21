"""Tests pinning the one report-path naming rule."""

from __future__ import annotations

import pytest

from ncs_reporter.models.node_path import NodePath, slugify


class TestSlugify:
    def test_lowercases_and_hyphenates(self) -> None:
        assert slugify("My Datacenter") == "my-datacenter"

    def test_collapses_non_alnum_runs(self) -> None:
        assert slugify("prod / east (1)") == "prod-east-1"

    def test_strips_edge_hyphens(self) -> None:
        assert slugify("   lab-01   ") == "lab-01"

    def test_empty_result_raises(self) -> None:
        with pytest.raises(ValueError):
            slugify("!!!")

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError):
            slugify(None)  # type: ignore[arg-type]


class TestNodePathRootAndProduct:
    def test_site_is_the_only_hardcoded_name(self) -> None:
        root = NodePath.site()
        assert root.html_path.as_posix() == "site.html"
        assert root.variant_path("stig").as_posix() == "site.stig.html"

    def test_product_directory_self_names(self) -> None:
        vsphere = NodePath.product("vsphere")
        assert vsphere.html_path.as_posix() == "vsphere/vsphere.html"
        assert vsphere.directory.as_posix() == "vsphere"

    def test_child_deepens_path(self) -> None:
        esxi = (
            NodePath.product("vsphere")
            .child("vc-prod-01")
            .child("dc-east")
            .child("cluster-01")
            .child("esxi-01")
        )
        assert esxi.html_path.as_posix() == "vsphere/vc-prod-01/dc-east/cluster-01/esxi-01/esxi-01.html"


class TestNodePathArtifacts:
    @pytest.fixture
    def esxi(self) -> NodePath:
        return (
            NodePath.product("vsphere")
            .child("vc-prod-01")
            .child("dc-east")
            .child("cluster-01")
            .child("esxi-01")
        )

    def test_primary_html(self, esxi: NodePath) -> None:
        assert esxi.html_path.as_posix().endswith("/esxi-01/esxi-01.html")

    def test_stig_variant(self, esxi: NodePath) -> None:
        assert esxi.variant_path("stig").as_posix().endswith("/esxi-01/esxi-01.stig.html")

    def test_historical_snapshot(self, esxi: NodePath) -> None:
        assert esxi.history_path("20260421T090000Z").as_posix().endswith(
            "/esxi-01/history/20260421T090000Z.html"
        )

    def test_raw_yaml_lives_in_node_directory(self, esxi: NodePath) -> None:
        assert esxi.raw_path.as_posix().endswith("/esxi-01/raw.yaml")

    def test_raw_stig_variant(self, esxi: NodePath) -> None:
        assert esxi.raw_variant_path("stig").as_posix().endswith("/esxi-01/raw.stig.yaml")

    def test_state_file(self, esxi: NodePath) -> None:
        assert esxi.state_path.as_posix().endswith("/esxi-01/state.yaml")

    def test_variant_requires_identifier(self, esxi: NodePath) -> None:
        with pytest.raises(ValueError):
            esxi.variant_path("bad variant")


class TestNodePathNavigation:
    def test_ancestors_walk_to_root(self) -> None:
        esxi = NodePath.product("vsphere").child("vc-01").child("dc-1").child("cluster-A").child("esxi-1")
        ancestors = esxi.ancestors()
        assert [a.slug for a in ancestors] == ["vsphere", "vc-01", "dc-1", "cluster-A"]

    def test_site_has_no_parent(self) -> None:
        assert NodePath.site().parent() is None

    def test_resolve_under_gives_absolute_path(self, tmp_path) -> None:
        node = NodePath.product("ubuntu").child("web-01")
        resolved = node.resolve_under(tmp_path)
        assert resolved == tmp_path / "ubuntu" / "web-01"

    def test_site_resolve_is_root(self, tmp_path) -> None:
        assert NodePath.site().resolve_under(tmp_path) == tmp_path


class TestNodePathEquality:
    def test_same_segments_equal(self) -> None:
        a = NodePath.product("vsphere").child("vc-01")
        b = NodePath.product("vsphere").child("vc-01")
        assert a == b and hash(a) == hash(b)

    def test_different_segments_not_equal(self) -> None:
        assert NodePath.product("vsphere") != NodePath.product("ubuntu")

    def test_construction_rejects_empty_segment(self) -> None:
        with pytest.raises(ValueError):
            NodePath(["vsphere", "", "vc-01"])

    def test_construction_rejects_empty_tuple(self) -> None:
        with pytest.raises(ValueError):
            NodePath([])
