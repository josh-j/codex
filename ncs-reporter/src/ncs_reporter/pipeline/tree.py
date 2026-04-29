"""Tree-layout orchestration for the full report pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from .._report_context import ReportContext, get_jinja_env
from ..aggregation import deep_merge, normalize_host_bundle
from .history import (
    HISTORY_DIR,
    _read_archive_stamp_manifests,
    _refresh_archive_history_dropdowns,
    _refresh_history_index,
    _write_stamp_manifest,
)
from ..models.tree import build_tree_from_spec
from ..schema_loader import discover_schemas
from ..view_models.tree_render import _attach_alert_rollups, _compute_tree_state, render_tree


def _render_inventory_trees(
    r_root: Path,
    all_platform_data: dict[str, dict[str, Any]],
    extra_dirs: tuple[str, ...],
    common_vars: dict[str, Any],
    *,
    bundle_root: Path | None = None,
) -> tuple[list[tuple[str, str, Path, list[str]]], dict[str, str], list[dict[str, str]]]:
    """Render the hierarchical inventory trees (vSphere + flat products)."""
    del all_platform_data  # retained for backwards-compatible callers
    b_root = bundle_root or r_root

    schemas = discover_schemas(extra_dirs=extra_dirs)
    env = get_jinja_env()
    ctx = ReportContext(report_stamp=common_vars.get("report_stamp", ""))
    rendered: list[tuple[str, str, Path, list[str]]] = []
    host_urls: dict[str, str] = {}

    def _record_host_urls(root_node: Any) -> None:
        for node in root_node.walk():
            if node.is_root:
                continue
            rel = node.node_path.resolve_under(r_root).relative_to(r_root) / f"{node.slug}.html"
            host_urls.setdefault(str(node.title or node.slug), rel.as_posix())

    tree_specs: list[tuple[str, str, Any, list[str]]] = []
    seen_roots: set[str] = set()
    for schema in schemas.values():
        if schema.tree is None:
            continue
        spec = schema.tree
        if spec.root_slug in seen_roots:
            continue
        seen_roots.add(spec.root_slug)
        tree_root = build_tree_from_spec(spec, bundles_root=b_root)
        if tree_root is None:
            continue
        host_ids = sorted(n.title or n.slug for n in tree_root.walk() if not n.is_root)
        tree_specs.append((spec.root_slug, spec.root_title or spec.root_slug, tree_root, host_ids))

    tree_products = [
        {"slug": slug, "name": title, "report": f"{slug}/{slug}.html"}
        for slug, title, _, _ in tree_specs
    ]

    current_stamp = (common_vars.get("report_stamp") or "").strip()
    archive_stamps = _read_archive_stamp_manifests(r_root)
    live_paths: list[str] = []
    for _slug, _title, tree_root, _host_ids in tree_specs:
        for n in tree_root.walk():
            live_paths.append(n.node_path.html_path.as_posix())
    history_for_render: list[dict[str, Any]] = []
    if current_stamp:
        history_for_render.append({
            "stamp": current_stamp,
            "label": "Latest",
            "is_latest": True,
            "paths": live_paths,
        })
    history_for_render.extend(archive_stamps)

    tree_states: dict[str, dict[int, dict[str, Any]]] = {}
    for slug, title, tree_root, host_ids in tree_specs:
        tree_states[slug] = _compute_tree_state(tree_root, schemas)
        _attach_alert_rollups(tree_root, tree_states[slug])
        written = render_tree(
            tree_root,
            schemas_by_name=schemas,
            env=env,
            output_root=r_root,
            ctx=ctx,
            tree_products=tree_products,
            stamp_prefix="",
            history_stamps=history_for_render,
            tree_state=tree_states[slug],
        )
        click.echo(f"--- Inventory tree: {slug} ({len(written)} node{'s' if len(written) != 1 else ''}) ---")
        if written:
            rendered.append((slug, title, written[0], host_ids))
            _record_host_urls(tree_root)

    if current_stamp:
        archive_root = r_root / HISTORY_DIR / current_stamp
        archive_ctx = ReportContext(report_stamp=current_stamp)
        archive_stamp_prefix = f"{HISTORY_DIR}/{current_stamp}/"
        for slug, _title, tree_root, _host_ids in tree_specs:
            render_tree(
                tree_root,
                schemas_by_name=schemas,
                env=env,
                output_root=archive_root,
                ctx=archive_ctx,
                tree_products=tree_products,
                stamp_prefix=archive_stamp_prefix,
                history_stamps=history_for_render,
                tree_state=tree_states.get(slug),
            )
        _write_stamp_manifest(archive_root, current_stamp, live_paths)
        archive_stamps = _read_archive_stamp_manifests(r_root)
        _refresh_history_index(r_root, archive_stamps)

    if history_for_render:
        _refresh_archive_history_dropdowns(r_root, history_for_render)

    return rendered, host_urls, tree_products


def _read_bundle_data(path: Path) -> dict[str, Any] | None:
    """Read a collector-emitted ``raw.yaml`` and return its ``.data`` dict."""
    try:
        with path.open(encoding="utf-8") as f:
            bundle = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(bundle, dict):
        return None
    data = bundle.get("data")
    return data if isinstance(data, dict) else None


def _collect_tree_leaf_bundles(
    reports_root: Path,
    root_slug: str,
) -> dict[str, dict[str, Any]]:
    """Return ``raw.yaml`` data for every leaf bundle under one product root."""
    product_dir = reports_root / root_slug
    if not product_dir.is_dir():
        return {}
    all_paths = sorted(product_dir.rglob("raw.yaml"))
    parent_dirs = {p.parent for p in all_paths}
    ancestor_dirs = {a for d in parent_dirs for a in d.parents}
    leaf_dirs = parent_dirs - ancestor_dirs
    leaf_bundles: dict[str, dict[str, Any]] = {}
    for raw_path in all_paths:
        if raw_path.parent not in leaf_dirs:
            continue
        data = _read_bundle_data(raw_path)
        if data is not None:
            leaf_bundles[raw_path.parent.name] = data
    return leaf_bundles


def _merge_tree_bundles_into_global(
    reports_root: Path,
    global_data: dict[str, Any],
    global_inventory_index: dict[str, str],
    *,
    extra_dirs: tuple[str, ...] = (),
) -> None:
    """Hydrate ``global_data['hosts']`` with tree-layout raw bundles."""
    if not reports_root.is_dir():
        return
    touched: set[str] = set()

    schemas = discover_schemas(extra_dirs=extra_dirs)
    seen_roots: set[str] = set()

    for schema in schemas.values():
        if schema.tree is None or not schema.tree.levels:
            continue
        spec = schema.tree
        if spec.root_slug in seen_roots:
            continue
        seen_roots.add(spec.root_slug)
        leaf_level = spec.levels[-1]
        leaf_bundle_key = leaf_level.bundle_key
        leaf_schema = schemas.get(leaf_level.schema_name)
        leaf_report_dir = (leaf_schema.platform if leaf_schema else "") or spec.root_slug
        for hostname, data in _collect_tree_leaf_bundles(reports_root, spec.root_slug).items():
            entry = global_data["hosts"].setdefault(hostname, {})
            deep_merge(entry, {leaf_bundle_key: {"data": data}})
            global_inventory_index.setdefault(hostname, leaf_report_dir)
            touched.add(hostname)

    if not touched:
        return
    for hostname in touched:
        global_data["hosts"][hostname] = normalize_host_bundle(
            hostname, global_data["hosts"][hostname], extra_dirs=extra_dirs
        )
    global_data["metadata"]["fleet_stats"]["total_hosts"] = len(global_data["hosts"])
    click.echo(f"  Hydrated {len(touched)} host(s) from tree-layout bundles.")
