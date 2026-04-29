"""Per-instance report tree.

The :class:`ReportNode` model represents a single node in the rendered report
tree — a product root (vSphere, Ubuntu, Photon, Windows Server, ACI), an
intermediate tier (vCenter, Datacenter, Cluster), or a leaf (ESXi host, Linux
host, Windows host, APIC). Unlike :class:`~.platforms_config.PlatformNode`
(schema-level metadata), ``ReportNode`` is materialized from actual collected
bundles — one node per vCenter, one per datacenter, etc.

Paths follow the single naming rule enforced by :mod:`~.node_path`.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import yaml

from .node_path import NodePath, slugify

logger = logging.getLogger("ncs_reporter")


@dataclasses.dataclass
class ReportNode:
    """A single node in the per-instance report tree.

    Attributes
    ----------
    tier:
        Role in the hierarchy: ``inventory`` (root product), ``vcenter``,
        ``datacenter``, ``cluster``, ``esxi_host``, ``host`` (flat-product leaf).
    slug:
        Path segment for this node. Always the last segment of ``node_path``.
    title:
        Human-readable display name. Defaults to ``slug`` if not supplied.
    schema_name:
        Name of the reporter schema that renders this node (e.g. ``vsphere``,
        ``vcsa``, ``datacenter``, ``cluster``, ``esxi``, ``ubuntu``).
    node_path:
        The node's :class:`NodePath`. Its ``.html_path`` is where the report
        lands; its ``.raw_path`` is where the collector wrote telemetry.
    parent:
        Parent node, or ``None`` for tree roots (inventory tier).
    children:
        Direct descendants. Populated by the tree assembler.
    data_source:
        Callable returning the fields dict for this node when rendered.
        Takes the aggregated hosts payload; returns a dict the schema's
        widgets + alerts evaluate against. ``None`` for synthetic nodes
        whose data is purely derived from children.
    """

    tier: str
    slug: str
    schema_name: str
    node_path: NodePath
    title: str = ""
    parent: ReportNode | None = None
    children: list[ReportNode] = dataclasses.field(default_factory=list)
    data_source: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.slug

    # -- accessors ---------------------------------------------------------

    @property
    def is_root(self) -> bool:
        return self.parent is None

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def ancestors(self) -> list[ReportNode]:
        """Walk up to root — returns [root, ..., parent]. Excludes self."""
        result: list[ReportNode] = []
        node = self.parent
        while node is not None:
            result.append(node)
            node = node.parent
        result.reverse()
        return result

    def walk(self) -> Iterator[ReportNode]:
        """Pre-order traversal of this subtree."""
        yield self
        for child in self.children:
            yield from child.walk()

    def add_child(self, child: ReportNode) -> ReportNode:
        child.parent = self
        self.children.append(child)
        return child

    def find_or_add_child(
        self,
        slug: str,
        *,
        tier: str,
        schema_name: str,
        title: str = "",
        data_source: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> ReportNode:
        """Return the child with ``slug`` if it exists, else create and attach."""
        for c in self.children:
            if c.slug == slug:
                return c
        child = ReportNode(
            tier=tier,
            slug=slug,
            title=title or slug,
            schema_name=schema_name,
            node_path=self.node_path.child(slug),
            data_source=data_source,
        )
        return self.add_child(child)


# ---------------------------------------------------------------------------
# Tree assembly — turns collected bundles into a ReportNode hierarchy.
# ---------------------------------------------------------------------------


def _static_source(data: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a data_source callable that yields *data* regardless of input."""
    def _src(_aggregated: dict[str, Any]) -> dict[str, Any]:
        return data
    return _src


# ---------------------------------------------------------------------------
# Internal placement helpers.
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_tree_from_spec(
    spec: Any,
    *,
    bundles_root: Path,
) -> ReportNode | None:
    """Build a ``ReportNode`` tree by walking ``bundles_root/<root_slug>/``
    and matching each ``raw.yaml`` to a level declared on *spec*.

    *spec* is a ``TreeSpec`` (or compatible duck-typed object) carrying
    ``root_slug``, ``root_title``, and a list of ``levels``. The reporter
    stays product-agnostic: every assumption about *which* tiers exist
    and *where* on disk their bundles land comes from the spec, not from
    Python.

    Levels are matched to bundles by **path depth below ``root_slug``**:
    the first level handles depth-1 bundles (``<root_slug>/<a>/raw.yaml``),
    subsequent levels handle deeper depths. ``parent_tier`` resolves which
    earlier level a child attaches to; the parent's slug is taken from
    the segment at index 0 of the bundle's path (i.e. the first segment
    below the product root).
    """
    if spec is None or not getattr(spec, "root_slug", None):
        return None
    root_slug = spec.root_slug
    product_dir = bundles_root / root_slug
    if not product_dir.is_dir():
        return None

    root = ReportNode(
        tier="inventory",
        slug=root_slug,
        title=getattr(spec, "root_title", "") or root_slug,
        schema_name=getattr(spec, "root_schema", "") or root_slug,
        node_path=NodePath.product(root_slug),
    )

    levels = list(getattr(spec, "levels", []) or [])
    if not levels:
        return root

    nodes_by_segments: dict[tuple[str, ...], ReportNode] = {}
    found_bundles: list[tuple[tuple[str, ...], dict[str, Any], Any]] = []
    for raw_path in sorted(product_dir.rglob("raw.yaml")):
        rel_segments = raw_path.parent.relative_to(product_dir).parts
        if not rel_segments:
            continue
        level = _select_level_for_depth(levels, depth=len(rel_segments))
        if level is None:
            continue
        data = _read_yaml_data(raw_path)
        if not isinstance(data, dict):
            continue
        found_bundles.append((rel_segments, data, level))

    found_bundles.sort(key=lambda entry: (len(entry[0]), entry[0]))

    for rel_segments, data, level in found_bundles:
        parent = _resolve_parent_for_level(level, rel_segments, root, nodes_by_segments)
        if parent is None:
            continue
        host_slug = slugify(rel_segments[-1])
        # Use the directory segment as title so host_urls / tree_products /
        # site dashboard all key against the same string; metadata.host may
        # carry a dotted form that doesn't match the slugified inventory key.
        title = rel_segments[-1]
        bundle_envelope = {
            level.bundle_key: {
                "data": data.get("data") if isinstance(data.get("data"), dict) else data,
                "metadata": data.get("metadata") or {"host": title},
            },
        }
        node = parent.find_or_add_child(
            host_slug,
            tier=level.tier,
            schema_name=level.schema_name,
            title=title,
            data_source=_static_source(bundle_envelope),
        )
        nodes_by_segments[tuple(rel_segments)] = node

    # Generic per-tier rollup so the root page can render an Inventory
    # widget driven purely by the spec. For each declared tier ``T``,
    # expose ``<T>s: [...]`` (list of {title, report_url, _node_ref})
    # and ``<T>_count`` on root.data_source. ``hosts`` / ``host_count``
    # are also emitted as aliases for the deepest tier so legacy
    # ``inventory_root.yaml`` widgets keep working.
    rollup: dict[str, Any] = {}
    for level in levels:
        tier_nodes = [n for n in root.walk() if n.tier == level.tier]
        rows = [
            {
                "title": n.title or n.slug,
                "name": n.title or n.slug,
                "report_url": "/".join(n.node_path.segments[1:]) + f"/{n.slug}.html",
                "_node_ref": id(n),
            }
            for n in tier_nodes
        ]
        rollup[f"{level.tier}s"] = rows
        rollup[f"{level.tier}_count"] = len(rows)
    if levels:
        deepest_tier = levels[-1].tier
        rollup["hosts"] = rollup.get(f"{deepest_tier}s", [])
        rollup["host_count"] = rollup.get(f"{deepest_tier}_count", 0)

    # Cross-tier list unions: each ``merge_from_children`` directive
    # concatenates a list field resolved by dotted path inside every
    # first-level child's bundle.
    from ..normalization._fields import resolve_field
    for merge in (getattr(spec, "merge_from_children", None) or []):
        if not merge.from_:
            continue
        union: list[Any] = []
        for child in root.children:
            bundle = child.data_source({}) if child.data_source else {}
            value = resolve_field(merge.from_, bundle)
            if isinstance(value, list):
                union.extend(value)
        rollup[merge.field] = union
        rollup.setdefault(f"{merge.field}_count", len(union))

    root.data_source = _static_source(rollup)

    return root


def _select_level_for_depth(levels: list[Any], *, depth: int) -> Any | None:
    """Pick the TreeLevel that handles a bundle at the given path depth.

    First level (index 0) handles depth-1 bundles; subsequent levels
    handle deeper bundles. Anything below the deepest declared level
    is treated as a leaf belonging to that level.
    """
    if not levels:
        return None
    if depth <= 1:
        return levels[0]
    if depth - 1 < len(levels):
        return levels[depth - 1]
    return levels[-1]


def _resolve_parent_for_level(
    level: Any,
    rel_segments: tuple[str, ...],
    root: ReportNode,
    nodes_by_segments: dict[tuple[str, ...], ReportNode],
) -> ReportNode | None:
    parent_tier = getattr(level, "parent_tier", None)
    if not parent_tier or len(rel_segments) <= 1:
        return root
    # parent_segment_index defaults to 0 — the first segment below the
    # product root identifies the parent slug for any deeper level.
    parent_idx = getattr(level, "parent_segment_index", 0) or 0
    parent_segments = tuple(rel_segments[: parent_idx + 1])
    parent = nodes_by_segments.get(parent_segments)
    if parent is None:
        logger.warning(
            "build_tree_from_spec: no parent at %s for child %s",
            "/".join(parent_segments), "/".join(rel_segments),
        )
    return parent


def _read_yaml_data(path: Path) -> dict[str, Any] | None:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except Exception:
        logger.exception("Failed to read tree bundle %s", path)
        return None
    return data if isinstance(data, dict) else None
