"""Unit tests for the history orchestration helpers in ``_cli_all``."""

from __future__ import annotations

import json
from pathlib import Path

from ncs_reporter._cli_all import (
    _format_stamp_label,
    _history_for_render_signature,
    _patch_history_groups_in_html,
    _read_archive_stamp_manifests,
    _refresh_archive_history_dropdowns,
    _refresh_history_index,
    _write_stamp_manifest,
)


class TestFormatStampLabel:
    def test_yyyymmdd_becomes_dashed(self):
        assert _format_stamp_label("20260301") == "2026-03-01"

    def test_non_date_passes_through(self):
        assert _format_stamp_label("custom") == "custom"
        assert _format_stamp_label("2026-03-01") == "2026-03-01"


class TestStampManifest:
    def test_round_trip(self, tmp_path: Path):
        target = tmp_path / "history" / "20260101"
        paths = ["site.html", "vsphere/vsphere.html", "vsphere/host/host.html"]
        _write_stamp_manifest(target, "20260101", paths)
        data = json.loads((target / "manifest.json").read_text())
        assert data["stamp"] == "20260101"
        assert data["paths"] == sorted(paths)
        assert "rendered_at" in data and data["rendered_at"]

    def test_paths_are_deduped_and_sorted(self, tmp_path: Path):
        target = tmp_path / "history" / "20260101"
        _write_stamp_manifest(target, "20260101", ["b.html", "a.html", "a.html"])
        data = json.loads((target / "manifest.json").read_text())
        assert data["paths"] == ["a.html", "b.html"]


class TestReadArchiveStampManifests:
    def test_returns_newest_first(self, tmp_path: Path):
        for stamp in ("20260101", "20260301", "20260201"):
            _write_stamp_manifest(tmp_path / "history" / stamp, stamp, ["site.html"])
        out = _read_archive_stamp_manifests(tmp_path)
        assert [e["stamp"] for e in out] == ["20260301", "20260201", "20260101"]

    def test_empty_when_no_history(self, tmp_path: Path):
        assert _read_archive_stamp_manifests(tmp_path) == []

    def test_skips_unparseable_manifests(self, tmp_path: Path):
        good = tmp_path / "history" / "20260101"
        _write_stamp_manifest(good, "20260101", ["site.html"])
        bad = tmp_path / "history" / "20260201"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text("{not json")
        out = _read_archive_stamp_manifests(tmp_path)
        # The bad manifest is silently skipped — we must not blow up the run.
        assert [e["stamp"] for e in out] == ["20260101"]

    def test_label_is_human_friendly(self, tmp_path: Path):
        _write_stamp_manifest(tmp_path / "history" / "20260301", "20260301", ["site.html"])
        out = _read_archive_stamp_manifests(tmp_path)
        assert out[0]["label"] == "2026-03-01"


class TestHistoryIndex:
    def test_writes_newest_first(self, tmp_path: Path):
        for stamp in ("20260101", "20260301", "20260201"):
            _write_stamp_manifest(tmp_path / "history" / stamp, stamp, ["site.html"])
        _refresh_history_index(tmp_path)
        idx = json.loads((tmp_path / "history" / "index.json").read_text())
        assert [s["stamp"] for s in idx["stamps"]] == ["20260301", "20260201", "20260101"]
        assert all("rendered_at" in s for s in idx["stamps"])

    def test_noop_without_history_dir(self, tmp_path: Path):
        _refresh_history_index(tmp_path)  # must not raise
        assert not (tmp_path / "history").exists()


class TestPatchHistoryGroupsInHtml:
    """The post-render pass rewrites History sub-groups inside archived
    pages so older archives stay in lock-step as new stamps land.
    The marker is ``data-history-path`` on the History group's div."""

    def _archive_html_skeleton(self, html_path: str, stale_items: str) -> str:
        # Mimics the breadcrumb the template emits, with a single
        # History subgroup for *html_path* and *stale_items* inside.
        return (
            '<div class="breadcrumb">'
            '<div class="nav-tree">'
            '<a href="..." class="tree-label">vc-prod-01</a>'
            '<span class="tree-trigger">v</span>'
            '<div class="nav-dropdown">'
            f'<div class="dropdown-group" data-history-path="{html_path}">History</div>'
            f'{stale_items}'
            '</div></div></div>'
        )

    def test_replaces_stale_items_with_current_stamps(self):
        html_path = "vsphere/vc-prod-01/vc-prod-01.html"
        stale = '<a href="#" class="active">2026-01-01</a>'
        content = self._archive_html_skeleton(html_path, stale)
        history_for_render = [
            {"stamp": "20260301", "label": "Latest", "is_latest": True,
             "paths": [html_path]},
            {"stamp": "20260201", "label": "2026-02-01", "paths": [html_path]},
            {"stamp": "20260101", "label": "2026-01-01", "paths": [html_path]},
        ]
        out = _patch_history_groups_in_html(
            content,
            history_for_render=history_for_render,
            stamp_prefix="history/20260101/",
            back_to_root="../../../../",
        )
        # New stamp 20260301 must appear; the page is at 20260101 so that
        # one is active.
        assert "Latest" in out
        assert "2026-02-01" in out
        assert 'href="#" class="active"' in out  # the 20260101 entry
        assert "../../../../vsphere/vc-prod-01/vc-prod-01.html" in out  # Latest link

    def test_diverged_node_renders_as_disabled_span(self):
        html_path = "vsphere/vc-prod-01/vc-prod-01.html"
        stale = '<a href="#" class="active">2026-01-01</a>'
        content = self._archive_html_skeleton(html_path, stale)
        # The new stamp's manifest doesn't include this node.
        history_for_render = [
            {"stamp": "20260301", "label": "Latest", "is_latest": True,
             "paths": ["site.html", "vsphere/vsphere.html"]},
            {"stamp": "20260101", "label": "2026-01-01", "paths": [html_path]},
        ]
        out = _patch_history_groups_in_html(
            content,
            history_for_render=history_for_render,
            stamp_prefix="history/20260101/",
            back_to_root="../../../../",
        )
        # Latest is greyed out — the page no longer exists in the live tree.
        assert "dropdown-disabled" in out
        assert "Not rendered in this snapshot" in out

    def test_blocks_without_marker_are_left_alone(self):
        # Old-style breadcrumb (pre data-history-path) must not blow up.
        content = (
            '<div class="dropdown-group">History</div>'
            '<a href="x.html">2026-01-01</a></div>'
        )
        out = _patch_history_groups_in_html(
            content,
            history_for_render=[{"stamp": "20260101", "is_latest": True, "paths": []}],
            stamp_prefix="",
            back_to_root="",
        )
        assert out == content


class TestRefreshArchiveHistoryDropdowns:
    """Verify the refresh pass skips the rglob walk when the stamp set
    hasn't changed since the last run, and re-runs when it has."""

    def _make_archive_page(self, tmp_path: Path, stamp: str, html_path: str, items_html: str) -> Path:
        page = tmp_path / "history" / stamp / html_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            '<div class="dropdown-group" data-history-path="' + html_path + '">History</div>'
            f'{items_html}</div>'
        )
        return page

    def _history(self, stamp: str, html_paths: list[str], is_latest: bool = False) -> dict:
        e = {"stamp": stamp, "label": stamp, "paths": html_paths}
        if is_latest:
            e["is_latest"] = True
        return e

    def test_skips_when_signature_unchanged(self, tmp_path: Path):
        page = self._make_archive_page(
            tmp_path, "20260101", "vsphere/vsphere.html",
            '<a href="#" class="active">2026-01-01</a>',
        )
        history = [
            self._history("20260301", ["vsphere/vsphere.html"], is_latest=True),
            self._history("20260101", ["vsphere/vsphere.html"]),
        ]
        # First refresh: walks and rewrites.
        _refresh_archive_history_dropdowns(tmp_path, history)
        first_mtime = page.stat().st_mtime_ns
        # Touch the file backwards in time so we can detect a re-walk.
        import os
        os.utime(page, ns=(first_mtime, first_mtime))
        # Second refresh with same history: should be a no-op.
        _refresh_archive_history_dropdowns(tmp_path, history)
        assert page.stat().st_mtime_ns == first_mtime

    def test_walks_when_stamp_set_changes(self, tmp_path: Path):
        page = self._make_archive_page(
            tmp_path, "20260101", "vsphere/vsphere.html",
            '<a href="#" class="active">stub</a>',
        )
        # v1: only the new live stamp exists, no archive entry yet.
        history_v1 = [
            self._history("20260101", ["vsphere/vsphere.html"], is_latest=True),
        ]
        _refresh_archive_history_dropdowns(tmp_path, history_v1)
        v1_content = page.read_text()
        # v2: a newer live stamp with 20260101 demoted to an archive entry.
        history_v2 = [
            self._history("20260201", ["vsphere/vsphere.html"], is_latest=True),
            self._history("20260101", ["vsphere/vsphere.html"]),
        ]
        _refresh_archive_history_dropdowns(tmp_path, history_v2)
        v2_content = page.read_text()
        assert v1_content != v2_content
        # The 20260101 archive entry should now be present + active.
        assert "20260101" in v2_content
        assert 'class="active"' in v2_content


class TestHistoryForRenderSignature:
    def test_stable_across_equivalent_inputs(self):
        a = [{"stamp": "x", "paths": ["a.html", "b.html"]}]
        b = [{"stamp": "x", "paths": ["b.html", "a.html"]}]  # path order
        assert _history_for_render_signature(a) == _history_for_render_signature(b)

    def test_changes_when_stamp_added(self):
        a = [{"stamp": "x", "paths": ["a.html"]}]
        b = [{"stamp": "x", "paths": ["a.html"]}, {"stamp": "y", "paths": ["a.html"]}]
        assert _history_for_render_signature(a) != _history_for_render_signature(b)

    def test_changes_when_paths_diverge(self):
        a = [{"stamp": "x", "paths": ["a.html"]}]
        b = [{"stamp": "x", "paths": ["b.html"]}]
        assert _history_for_render_signature(a) != _history_for_render_signature(b)
