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


def build_vsphere_tree(
    *,
    vcenter_bundles: dict[str, dict[str, Any]],
    esxi_bundles: dict[str, dict[str, Any]],
    vm_bundles: dict[str, dict[str, Any]],
) -> ReportNode:
    """Materialize the vSphere → vCenter → Datacenter → Cluster → ESXi tree.

    Parameters
    ----------
    vcenter_bundles:
        Mapping of vCenter inventory hostname → ``raw_vcsa.data`` dict. Each
        carries ``clusters`` (keyed by cluster name, with a ``datacenter``
        field inside), ``datastores``, ``dvswitches``, etc.
    esxi_bundles:
        Mapping of ESXi hostname → ``raw_esxi.data`` dict. Each should
        expose ``cluster`` and ``datacenter`` fields for tree placement.
    vm_bundles:
        Mapping of vCenter inventory hostname → ``raw_vm.data`` dict
        (containing the ``virtual_machines`` list and ``snapshots_raw``).

    Returns
    -------
    A ``ReportNode`` rooted at the ``vsphere`` inventory. The root's subtree
    spans one child per vCenter bundle, etc.
    """
    root = ReportNode(
        tier="inventory",
        slug="vsphere",
        title="vSphere",
        schema_name="vsphere",
        node_path=NodePath.product("vsphere"),
    )
    # vSphere root IS the "vCenter Appliances" overview — it lists every
    # vCenter directly with links to each vCenter host report. No
    # intermediate vcsa_fleet tier; datacenter children of each vCenter
    # list their ESXi hosts with cluster as a column.

    vcenter_summaries: list[dict[str, Any]] = []

    for vc_host, vc_data in sorted(vcenter_bundles.items()):
        vc_slug = slugify(vc_host)
        vc_bundle = {"raw_vcsa": {"data": vc_data, "metadata": {"host": vc_host}}}
        vc_node = root.find_or_add_child(
            vc_slug,
            tier="vcenter",
            schema_name="vcsa",
            title=vc_host,
            data_source=_static_source(vc_bundle),
        )

        clusters_raw = vc_data.get("clusters")
        if isinstance(clusters_raw, list):
            clusters = {
                str(c["name"]): c
                for c in clusters_raw
                if isinstance(c, dict) and c.get("name")
            }
        elif isinstance(clusters_raw, dict):
            clusters = clusters_raw
        else:
            clusters = {}
        _attach_datacenters_and_esxi(vc_node, clusters, vc_data, esxi_bundles, vm_bundles, vc_host)

        # Datacenter count is derived from the unique ``datacenter`` field
        # on the vCenter's clusters; the tree itself no longer carries a
        # datacenter tier (vCenter → ESXi only).
        dc_names = {
            str(c.get("datacenter") or "").strip()
            for c in clusters.values()
            if isinstance(c, dict) and (c.get("datacenter") or "").strip()
        }
        vcenter_summaries.append({
            "title": vc_host,
            "report_url": f"{vc_slug}/{vc_slug}.html",
            "version": vc_data.get("appliance_version", ""),
            "health": vc_data.get("appliance_health_overall", "unknown"),
            "alert_counts": {"critical": 0, "warning": 0},
            "datacenter_count": len(dc_names),
            "esxi_host_count": len(vc_node.children),
        })

    total_datacenters = sum(e["datacenter_count"] for e in vcenter_summaries)
    total_esxi = sum(e["esxi_host_count"] for e in vcenter_summaries)
    total_vms = sum(
        len(_as_list((vm_bundles.get(host) or {}).get("virtual_machines")))
        for host in vcenter_bundles
    )

    # Flat per-tier rows so the vsphere root page can render dedicated
    # "Datacenters", "ESXi Hosts", "Virtual Machines" tables alongside
    # the vCenter Appliances widget — operators landing on vsphere.html
    # want a one-shot inventory list without drilling down.
    datacenters_flat: list[dict[str, Any]] = []
    esxi_hosts_flat: list[dict[str, Any]] = []
    virtual_machines_flat: list[dict[str, Any]] = []
    for vc_node in root.children:
        vc_data = vc_node.data_source({}).get("raw_vcsa", {}).get("data", {}) if vc_node.data_source else {}
        vc_label = vc_node.title or vc_node.slug
        # Datacenters are not tree nodes anymore; reconstruct flat rows
        # from the vCenter's clusters list (datacenter is a field on each
        # cluster). The Inventory widget's "Datacenters" section still
        # shows them with cluster/host counts.
        clusters_iter = vc_data.get("clusters")
        if isinstance(clusters_iter, list):
            cluster_dicts = [c for c in clusters_iter if isinstance(c, dict)]
        elif isinstance(clusters_iter, dict):
            cluster_dicts = [c for c in clusters_iter.values() if isinstance(c, dict)]
        else:
            cluster_dicts = []
        dc_index: dict[str, dict[str, int]] = {}
        for cluster in cluster_dicts:
            dc_name = str(cluster.get("datacenter") or "").strip()
            if not dc_name:
                continue
            entry = dc_index.setdefault(dc_name, {"cluster_count": 0, "esxi_host_count": 0})
            entry["cluster_count"] += 1
            entry["esxi_host_count"] += int(cluster.get("host_count") or 0)
        for dc_name, counts in sorted(dc_index.items()):
            datacenters_flat.append({
                "name": dc_name,
                "vcenter": vc_label,
                "report_url": f"{vc_node.slug}/{vc_node.slug}.html",
                "esxi_host_count": counts["esxi_host_count"],
                "cluster_count": counts["cluster_count"],
            })
        for esxi_node in vc_node.children:
            esxi_data = esxi_node.data_source({}).get("raw_esxi", {}).get("data", {}) if esxi_node.data_source else {}
            esxi_hosts_flat.append({
                "name": esxi_node.title or esxi_node.slug,
                "vcenter": vc_label,
                "datacenter": esxi_data.get("datacenter") or "—",
                "cluster": esxi_data.get("cluster") or "—",
                "report_url": f"{vc_node.slug}/{esxi_node.slug}/{esxi_node.slug}.html",
                "version": esxi_data.get("version", ""),
                "overall_status": esxi_data.get("overall_status", "unknown"),
                "_node_ref": id(esxi_node),
            })
            for vm in _as_list(esxi_data.get("virtual_machines")):
                if isinstance(vm, dict):
                    virtual_machines_flat.append({
                        "name": vm.get("guest_name") or vm.get("name") or "",
                        "vcenter": vc_label,
                        "datacenter": esxi_data.get("datacenter") or "—",
                        "cluster": esxi_data.get("cluster") or "—",
                        "esxi_host": esxi_node.title or esxi_node.slug,
                        "esxi_host_url": (
                            f"{vc_node.slug}/{esxi_node.slug}/{esxi_node.slug}.html"
                        ),
                        "power_state": vm.get("power_state", ""),
                        "guest_os": vm.get("guest_fullname", ""),
                        "ip_address": vm.get("ip_address", ""),
                    })

    root.data_source = _static_source({
        "vcenters": vcenter_summaries,
        "datacenters": datacenters_flat,
        "esxi_hosts": esxi_hosts_flat,
        "virtual_machines": virtual_machines_flat,
        "datacenter_count": total_datacenters,
        "esxi_host_count": total_esxi,
        "vm_count": total_vms,
        "vcenter_count": len(vcenter_summaries),
    })

    return root


def _static_source(data: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a data_source callable that yields *data* regardless of input."""
    def _src(_aggregated: dict[str, Any]) -> dict[str, Any]:
        return data
    return _src


def _attach_datacenters_and_esxi(
    vc_node: ReportNode,
    clusters: dict[str, dict[str, Any]],
    vc_data: dict[str, Any],
    esxi_bundles: dict[str, dict[str, Any]],
    vm_bundles: dict[str, dict[str, Any]],
    vc_host: str,
) -> None:
    """Attach ESXi hosts directly under a vCenter node.

    The legacy ``vCenter → Datacenter → ESXi`` shape was flattened to
    ``vCenter → ESXi`` — datacenter info (clusters, datastores,
    dvswitches) is already on the vCenter's bundle and renders on the
    vCenter page, so a separate datacenter tier was redundant. ESXi
    rows still carry their datacenter name as a column for filter/sort.
    """
    vm_bundle = vm_bundles.get(vc_host, {})
    all_vms = _as_list(vm_bundle.get("virtual_machines"))

    vms_by_host: dict[str, list[dict[str, Any]]] = {}
    for vm in all_vms:
        if not isinstance(vm, dict):
            continue
        # The collector emits ``esxi_hostname`` (community.vmware naming);
        # accept either spelling for forward-compatibility.
        host_key = str(vm.get("esxi_hostname") or vm.get("esxi_host") or "").strip()
        vms_by_host.setdefault(host_key, []).append(vm)

    for esxi_host, esxi_data in sorted(esxi_bundles.items()):
        if not isinstance(esxi_data, dict):
            continue
        esxi_vms = vms_by_host.get(esxi_host, [])
        esxi_bundle = {
            "raw_esxi": {
                "data": {**esxi_data, "virtual_machines": esxi_vms},
                "metadata": {"host": esxi_host},
            },
        }
        vc_node.find_or_add_child(
            slugify(esxi_host),
            tier="esxi_host",
            schema_name="esxi",
            title=esxi_host,
            data_source=_static_source(esxi_bundle),
        )


def build_flat_inventory_tree(
    *,
    inventory_slug: str,
    title: str,
    schema_name: str,
    host_bundles: dict[str, dict[str, Any]],
    host_schema_name: str,
) -> ReportNode:
    """Materialize a flat inventory tree (Ubuntu, Photon, Windows, ACI).

    Each host becomes a direct child of the inventory root. Host data is
    wrapped as a ``raw_<schema>`` bundle so the existing host schema's
    path-based field extraction keeps working.
    """
    root = ReportNode(
        tier="inventory",
        slug=inventory_slug,
        title=title,
        schema_name="inventory_root",
        node_path=NodePath.product(inventory_slug),
    )
    raw_key = f"raw_{host_schema_name}"
    hosts_summary: list[dict[str, Any]] = []
    for host, data in sorted(host_bundles.items()):
        host_slug = slugify(host)
        wrapped = {raw_key: {"data": data, "metadata": {"host": host}}}
        root.find_or_add_child(
            host_slug,
            tier="host",
            schema_name=host_schema_name,
            title=host,
            data_source=_static_source(wrapped),
        )
        hosts_summary.append({"title": host, "report_url": f"{host_slug}/{host_slug}.html"})
    root.data_source = _static_source({"hosts": hosts_summary, "host_count": len(hosts_summary)})
    return root


# ---------------------------------------------------------------------------
# Internal placement helpers.
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_tree_from_spec(
    spec: Any,
    *,
    bundles_root: Path,
    augment: Callable[[ReportNode, dict[str, Any]], None] | None = None,
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

    *augment* is an optional per-product hook that runs after a node is
    placed in the tree, receiving the node and its raw data. The vSphere
    schema uses it to splice per-host VMs in from a sibling ``raw.vm.yaml``
    file. The hook lives in product-specific code (e.g. shipped alongside
    the schema YAML), not in ncs-reporter.
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
        schema_name=root_slug,
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
        title = (
            (data.get("metadata") or {}).get("host")
            if isinstance(data, dict) else None
        ) or rel_segments[-1]
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
        if augment is not None:
            try:
                augment(node, data)
            except Exception:
                logger.exception("augment hook failed for %s", raw_path)

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
