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


@dataclasses.dataclass(frozen=True)
class _InferredLevel:
    tier: str
    schema_name: str
    bundle_key: str
    parent_tier: str | None = None
    children_label: str | None = None


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


def build_tree_from_folders(
    root_slug: str,
    *,
    root_title: str = "",
    root_schema: str = "",
    bundles_root: Path,
) -> ReportNode | None:
    """Build a ``ReportNode`` tree from the collector-written folder layout.

    The folder path is the tree shape. Bundle metadata chooses the raw bundle
    key/schema where possible; vSphere additionally supports graph artifacts
    that project child nodes not present as individual folders.
    """
    product_dir = bundles_root / root_slug
    if not product_dir.is_dir():
        return None

    root = ReportNode(
        tier="inventory",
        slug=root_slug,
        title=root_title or root_slug,
        schema_name=root_schema or _infer_root_schema(root_slug),
        node_path=NodePath.product(root_slug),
    )

    if root_slug == "vsphere":
        _build_vsphere_folder_tree(root, product_dir)
    else:
        _build_flat_folder_tree(root, root_slug, product_dir)

    if not root.children:
        return None
    _attach_root_rollups(root)
    return root


def _infer_root_schema(root_slug: str) -> str:
    return root_slug if root_slug == "vsphere" else "inventory_root"


def _build_flat_folder_tree(root: ReportNode, root_slug: str, product_dir: Path) -> None:
    for raw_path in sorted(product_dir.glob("*/raw.yaml")):
        raw = _read_yaml_data(raw_path)
        if not isinstance(raw, dict):
            continue
        rel_segments = raw_path.parent.relative_to(product_dir).parts
        if not rel_segments:
            continue
        title = rel_segments[-1]
        schema_name = _schema_name_for_bundle(raw, default=root_slug)
        bundle_key = _bundle_key_for_bundle(raw, default=f"raw_{schema_name}")
        root.find_or_add_child(
            slugify(title),
            tier="host",
            schema_name=schema_name,
            title=title,
            data_source=_static_source({_bundle_key(bundle_key): _bundle_envelope(raw, title)}),
        )


def _build_vsphere_folder_tree(root: ReportNode, product_dir: Path) -> None:
    nodes_by_segments: dict[tuple[str, ...], ReportNode] = {}

    for graph_path in sorted([*product_dir.rglob("inventory.yaml"), *product_dir.rglob("raw.yaml")]):
        raw = _read_yaml_data(graph_path)
        if not isinstance(raw, dict):
            continue
        graph_data: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else raw
        if not _is_vsphere_graph(graph_data):
            continue
        rel_segments = graph_path.parent.relative_to(product_dir).parts
        if not rel_segments:
            continue
        _add_vsphere_graph_projection(root, nodes_by_segments, rel_segments, graph_data, _vsphere_levels())

    for raw_path in sorted(product_dir.rglob("raw.yaml")):
        raw = _read_yaml_data(raw_path)
        if not isinstance(raw, dict):
            continue
        graph_data2: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else raw
        if _is_vsphere_graph(graph_data2):
            continue
        rel_segments = raw_path.parent.relative_to(product_dir).parts
        if not rel_segments:
            continue
        _add_vsphere_folder_bundle(root, nodes_by_segments, rel_segments, raw)


def _vsphere_levels() -> list[_InferredLevel]:
    return [
        _InferredLevel("vcenter", "vcsa", "raw_vcsa", children_label="Datacenters"),
        _InferredLevel("datacenter", "datacenter", "raw_datacenter", "vcenter", "Clusters"),
        _InferredLevel("cluster", "cluster", "raw_cluster", "datacenter", "ESXi Hosts"),
        _InferredLevel("esxi_host", "esxi", "raw_esxi", "cluster", "VMs"),
        _InferredLevel("vm", "vm", "raw_vm", "esxi_host"),
    ]


def _add_vsphere_folder_bundle(
    root: ReportNode,
    nodes_by_segments: dict[tuple[str, ...], ReportNode],
    rel_segments: tuple[str, ...],
    raw: dict[str, Any],
) -> None:
    if len(rel_segments) == 1:
        title = rel_segments[0]
        schema_name = _schema_name_for_bundle(raw, default="vcsa")
        bundle_key = _bundle_key_for_bundle(raw, default=f"raw_{schema_name}")
        node = root.find_or_add_child(
            slugify(title),
            tier="vcenter",
            schema_name=schema_name,
            title=title,
            data_source=_static_source({_bundle_key(bundle_key): _bundle_envelope(raw, title)}),
        )
        node.tier = "vcenter"
        node.schema_name = schema_name
        node.title = title
        node.data_source = _static_source({_bundle_key(bundle_key): _bundle_envelope(raw, title)})
        nodes_by_segments[(slugify(title),)] = node
        return

    parent = _ensure_vsphere_folder_parent(root, nodes_by_segments, rel_segments[:-1])
    if parent is None:
        return
    title = rel_segments[-1]
    tier, default_schema = _vsphere_leaf_identity(len(rel_segments))
    schema_name = _schema_name_for_bundle(raw, default=default_schema)
    bundle_key = _bundle_key_for_bundle(raw, default=f"raw_{schema_name}")
    node = parent.find_or_add_child(
        slugify(title),
        tier=tier,
        schema_name=schema_name,
        title=title,
        data_source=_static_source({_bundle_key(bundle_key): _bundle_envelope(raw, title)}),
    )
    node.tier = tier
    node.schema_name = schema_name
    node.title = title
    node.data_source = _static_source({_bundle_key(bundle_key): _bundle_envelope(raw, title)})
    nodes_by_segments[tuple(slugify(s) for s in rel_segments)] = node


def _ensure_vsphere_folder_parent(
    root: ReportNode,
    nodes_by_segments: dict[tuple[str, ...], ReportNode],
    rel_segments: tuple[str, ...],
) -> ReportNode | None:
    if not rel_segments:
        return root
    key = tuple(slugify(s) for s in rel_segments)
    existing = nodes_by_segments.get(key)
    if existing is not None:
        return existing

    parent = _ensure_vsphere_folder_parent(root, nodes_by_segments, rel_segments[:-1])
    if parent is None:
        return None
    title = rel_segments[-1]
    tier, schema_name = _vsphere_synthetic_identity(len(rel_segments))
    node = parent.find_or_add_child(
        slugify(title),
        tier=tier,
        schema_name=schema_name,
        title=title,
    )
    nodes_by_segments[key] = node
    return node


def _vsphere_synthetic_identity(depth: int) -> tuple[str, str]:
    if depth <= 1:
        return "vcenter", "vcsa"
    if depth == 2:
        return "datacenter", "datacenter"
    if depth == 3:
        return "cluster", "cluster"
    if depth == 4:
        return "esxi_host", "esxi"
    return "vm", "vm"


def _vsphere_leaf_identity(depth: int) -> tuple[str, str]:
    return _vsphere_synthetic_identity(depth)


def _schema_name_for_bundle(raw: dict[str, Any], *, default: str) -> str:
    md = raw.get("metadata")
    metadata: dict[str, Any] = md if isinstance(md, dict) else {}
    raw_type = str(metadata.get("raw_type") or "").strip()
    if raw_type:
        return raw_type
    audit_type = str(metadata.get("audit_type") or "").strip()
    if audit_type.startswith("raw_") and len(audit_type) > 4:
        return audit_type[4:]
    return default


def _bundle_key_for_bundle(raw: dict[str, Any], *, default: str) -> str:
    md = raw.get("metadata")
    metadata: dict[str, Any] = md if isinstance(md, dict) else {}
    audit_type = str(metadata.get("audit_type") or "").strip()
    if audit_type.startswith("raw_"):
        return audit_type
    raw_type = str(metadata.get("raw_type") or "").strip()
    if raw_type:
        return f"raw_{raw_type}"
    return default


def _bundle_key(value: str) -> str:
    return value if value.startswith("raw_") else f"raw_{value}"


def _bundle_envelope(raw: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "data": raw.get("data") if isinstance(raw.get("data"), dict) else raw,
        "metadata": raw.get("metadata") or {"host": title},
    }


def _attach_root_rollups(root: ReportNode, levels: list[Any] | None = None) -> None:
    rollup: dict[str, Any] = {}
    ordered_tiers = [str(getattr(level, "tier", "")) for level in (levels or []) if getattr(level, "tier", "")]
    if not ordered_tiers:
        seen: set[str] = set()
        for node in root.walk():
            if node.is_root or node.tier in seen:
                continue
            ordered_tiers.append(node.tier)
            seen.add(node.tier)

    for tier in ordered_tiers:
        tier_nodes = [n for n in root.walk() if n.tier == tier]
        rows = [
            {
                "title": n.title or n.slug,
                "name": n.title or n.slug,
                "report_url": "/".join(n.node_path.segments[1:]) + f"/{n.slug}.html",
                "_node_ref": id(n),
            }
            for n in tier_nodes
        ]
        rollup[f"{tier}s"] = rows
        rollup[f"{tier}_count"] = len(rows)

    leaf_nodes = [n for n in root.walk() if not n.is_root and n.is_leaf]
    rollup["hosts"] = [
        {
            "title": n.title or n.slug,
            "name": n.title or n.slug,
            "report_url": "/".join(n.node_path.segments[1:]) + f"/{n.slug}.html",
            "_node_ref": id(n),
        }
        for n in leaf_nodes
    ]
    rollup["host_count"] = len(rollup["hosts"])

    for child in root.children:
        bundle = child.data_source({}) if child.data_source else {}
        for payload in bundle.values():
            if not isinstance(payload, dict):
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            for key, value in data.items():
                if isinstance(value, list):
                    rollup.setdefault(key, []).extend(value)
    for key, value in list(rollup.items()):
        if isinstance(value, list):
            rollup.setdefault(f"{key}_count", len(value))

    root.data_source = _static_source(rollup)


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
        graph_data: dict[str, Any] = data["data"] if isinstance(data.get("data"), dict) else data
        if _is_vsphere_graph(graph_data):
            _add_vsphere_graph_projection(root, nodes_by_segments, rel_segments, graph_data, levels)
            continue
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

    _attach_root_rollups(root, levels)
    rollup = root.data_source({}) if root.data_source else {}

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
    for idx in range(len(rel_segments) - 1, 0, -1):
        candidate = nodes_by_segments.get(tuple(rel_segments[:idx]))
        if candidate is not None and candidate.tier == parent_tier:
            return candidate
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


def _level_by_tier(levels: list[Any]) -> dict[str, Any]:
    return {str(getattr(level, "tier", "")): level for level in levels}


def _is_vsphere_graph(data: Any) -> bool:
    return isinstance(data, dict) and data.get("kind") == "vsphere_graph"


def _add_vsphere_graph_projection(
    root: ReportNode,
    nodes_by_segments: dict[tuple[str, ...], ReportNode],
    rel_segments: tuple[str, ...],
    graph: dict[str, Any],
    levels: list[Any],
) -> None:
    levels_by_tier = _level_by_tier(levels)
    vc_level = levels_by_tier.get("vcenter")
    if vc_level is None:
        return

    vc_title = rel_segments[-1]
    vc_slug = slugify(vc_title)
    vcenter_data = _project_vcenter(graph, vc_title)
    vc_node = root.find_or_add_child(
        vc_slug,
        tier="vcenter",
        schema_name=vc_level.schema_name,
        title=vc_title,
        data_source=_static_source({vc_level.bundle_key: {"data": vcenter_data, "metadata": {"host": vc_title}}}),
    )
    vc_segments = (vc_slug,)
    nodes_by_segments[vc_segments] = vc_node

    dc_level = levels_by_tier.get("datacenter")
    cluster_level = levels_by_tier.get("cluster")
    host_level = levels_by_tier.get("esxi_host")
    vm_level = levels_by_tier.get("vm")

    datacenters = _as_list(graph.get("datacenters"))
    clusters = _as_list(graph.get("clusters"))
    hosts = _as_list(graph.get("hosts"))
    vms = _as_list(graph.get("vms"))

    dc_nodes: dict[str, ReportNode] = {}
    for dc in datacenters or [{"name": "default"}]:
        dc_name = str(dc.get("name") or "default")
        dc_slug = slugify(dc_name)
        if dc_level is None:
            dc_nodes[dc_name] = vc_node
            continue
        data = _project_datacenter(graph, dc_name)
        dc_node = vc_node.find_or_add_child(
            dc_slug,
            tier="datacenter",
            schema_name=dc_level.schema_name,
            title=dc_name,
            data_source=_static_source({dc_level.bundle_key: {"data": data, "metadata": {"host": dc_name}}}),
        )
        dc_nodes[dc_name] = dc_node
        nodes_by_segments[(vc_slug, dc_slug)] = dc_node

    cluster_nodes: dict[tuple[str, str], ReportNode] = {}
    for cluster in clusters:
        cluster_name = str(cluster.get("name") or "cluster")
        dc_name = str(cluster.get("datacenter") or (datacenters[0].get("name") if datacenters else "default"))
        parent = dc_nodes.get(dc_name) or vc_node
        if cluster_level is None:
            cluster_nodes[(dc_name, cluster_name)] = parent
            continue
        data = _project_cluster(graph, cluster)
        cluster_node = parent.find_or_add_child(
            slugify(cluster_name),
            tier="cluster",
            schema_name=cluster_level.schema_name,
            title=cluster_name,
            data_source=_static_source({cluster_level.bundle_key: {"data": data, "metadata": {"host": cluster_name}}}),
        )
        cluster_nodes[(dc_name, cluster_name)] = cluster_node
        nodes_by_segments[tuple([*parent.node_path.segments[1:], slugify(cluster_name)])] = cluster_node

    for host in hosts:
        host_name = str(host.get("name") or "host")
        dc_name = str(host.get("datacenter") or (datacenters[0].get("name") if datacenters else "default"))
        cluster_name = str(host.get("cluster") or "")
        parent = cluster_nodes.get((dc_name, cluster_name)) or dc_nodes.get(dc_name) or vc_node
        if host_level is None:
            continue
        host_node = parent.find_or_add_child(
            slugify(host_name),
            tier="esxi_host",
            schema_name=host_level.schema_name,
            title=host_name,
            data_source=_static_source({host_level.bundle_key: {"data": _project_host(graph, host), "metadata": {"host": host_name}}}),
        )
        nodes_by_segments[tuple([*parent.node_path.segments[1:], slugify(host_name)])] = host_node

        if vm_level is None:
            continue
        for vm in [row for row in vms if str(row.get("host") or "") == host_name]:
            vm_name = str(vm.get("name") or "vm")
            host_node.find_or_add_child(
                slugify(vm_name),
                tier="vm",
                schema_name=vm_level.schema_name,
                title=vm_name,
                data_source=_static_source({vm_level.bundle_key: {"data": _project_vm(graph, vm), "metadata": {"host": vm_name}}}),
            )


def _project_vcenter(graph: dict[str, Any], title: str) -> dict[str, Any]:
    counts = graph.get("metadata", {}).get("counts", {}) if isinstance(graph.get("metadata"), dict) else {}
    return {
        "appliance_version": "unknown",
        "appliance_build": "unknown",
        "appliance_health_overall": "unknown",
        "appliance_health_cpu": "unknown",
        "appliance_health_memory": "unknown",
        "appliance_health_database": "unknown",
        "appliance_health_storage": "unknown",
        "appliance_uptime_seconds": 0,
        "ssh_enabled": False,
        "shell_enabled": False,
        "ntp_mode": "unknown",
        "backup_schedules": [],
        "backup_schedule_count": 0,
        "datacenter_count": counts.get("datacenters", len(_as_list(graph.get("datacenters")))),
        "cluster_count": counts.get("clusters", len(_as_list(graph.get("clusters")))),
        "esxi_host_count": counts.get("hosts", len(_as_list(graph.get("hosts")))),
        "datastore_count": counts.get("datastores", len(_as_list(graph.get("datastores")))),
        "resource_pool_count": 0,
        "dvswitch_count": 0,
        "dvs_portgroup_count": 0,
        "license_count": 0,
        "extension_count": 0,
        "content_library_count": 0,
        "tag_category_count": 0,
        "tag_count": counts.get("tags", len(_as_list(graph.get("tags")))),
        "alarm_count": counts.get("alarms", len(_as_list(graph.get("alarms")))),
        "clusters": _as_list(graph.get("clusters")),
        "esxi_hosts": _as_list(graph.get("hosts")),
        "virtual_machines": _as_list(graph.get("vms")),
        "vm_count": counts.get("vms", len(_as_list(graph.get("vms")))),
        "vms_info_raw": {"virtual_machines": _as_list(graph.get("vms"))},
        "snapshots_raw": _as_list(graph.get("snapshots")),
        "snapshot_count": counts.get("snapshots", len(_as_list(graph.get("snapshots")))),
        "infra_patterns": [],
        "datastores": _as_list(graph.get("datastores")),
        "resource_pools": [],
        "dvswitches": [],
        "dvs_portgroups": [],
        "licenses": [],
        "extensions": [],
        "content_libraries": [],
        "tag_categories": [],
        "tags": _as_list(graph.get("tags")),
        "active_alarms": [
            {
                **alarm,
                "alarm_name": alarm.get("alarm_name") or alarm.get("message", ""),
                "description": alarm.get("description", ""),
            }
            for alarm in _as_list(graph.get("alarms"))
            if isinstance(alarm, dict)
        ],
        "config": {},
        "name": title,
    }


def _project_datacenter(graph: dict[str, Any], dc_name: str) -> dict[str, Any]:
    clusters = [_project_cluster(graph, c) for c in _as_list(graph.get("clusters")) if str(c.get("datacenter") or "") == dc_name]
    return {
        "datacenter_name": dc_name,
        "clusters": {str(c.get("name") or ""): c for c in clusters},
        "datastores": _as_list(graph.get("datastores")),
        "dvswitches": [],
        "esxi_hosts": [h for h in _as_list(graph.get("hosts")) if str(h.get("datacenter") or "") == dc_name],
        "esxi_host_count": len([h for h in _as_list(graph.get("hosts")) if str(h.get("datacenter") or "") == dc_name]),
    }


def _project_cluster(graph: dict[str, Any], cluster: dict[str, Any]) -> dict[str, Any]:
    name = str(cluster.get("name") or "")
    vms = [vm for vm in _as_list(graph.get("vms")) if str(vm.get("cluster") or "") == name]
    return {
        **cluster,
        "cluster_name": name,
        "host_count": len(_as_list(cluster.get("host_ids"))),
        "cpu_usage_pct": cluster.get("cpu_usage_pct", 0),
        "mem_usage_pct": cluster.get("mem_usage_pct", 0),
        "virtual_machines": vms,
    }


def _project_host(graph: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    host_name = str(host.get("name") or "")
    host_vms = [vm for vm in _as_list(graph.get("vms")) if str(vm.get("host") or "") == host_name]
    return {
        **host,
        "version": host.get("version", ""),
        "build": host.get("build", ""),
        "in_maintenance_mode": host.get("maintenance_mode", False),
        "lockdown_mode": host.get("lockdown_mode", "unknown"),
        "mem_used_pct": host.get("mem_used_pct", 0),
        "cpu_used_pct": host.get("cpu_used_pct", 0),
        "vm_count": len(host_vms),
        "uptime_seconds": host.get("uptime_seconds", 0),
        "ssh_enabled": host.get("ssh_enabled", False),
        "shell_enabled": host.get("shell_enabled", False),
        "ntp_running": host.get("ntp_running", False),
        "datastores": [],
        "nics": [],
        "virtual_machines": host_vms,
    }


def _project_vm(graph: dict[str, Any], vm: dict[str, Any]) -> dict[str, Any]:
    vm_name = str(vm.get("name") or "")
    snapshots = [s for s in _as_list(graph.get("snapshots")) if str(s.get("vm_name") or "") == vm_name]
    return {
        "datacenters": [],
        "virtual_machines": [vm],
        "vms_info_raw": {"virtual_machines": [vm]},
        "snapshots_raw": snapshots,
        "snapshot_count": len(snapshots),
        "vm_count": 1,
        "infra_patterns": [],
        "config": {},
    }


def _read_yaml_data(path: Path) -> dict[str, Any] | None:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except Exception:
        logger.exception("Failed to read tree bundle %s", path)
        return None
    return data if isinstance(data, dict) else None
