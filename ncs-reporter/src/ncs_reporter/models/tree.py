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
from collections.abc import Iterator
from typing import Any, Callable

from .node_path import NodePath, slugify


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

        vcenter_summaries.append({
            "title": vc_host,
            "report_url": f"{vc_slug}/{vc_slug}.html",
            "version": vc_data.get("appliance_version", ""),
            "health": vc_data.get("appliance_health_overall", "unknown"),
            "alert_counts": {"critical": 0, "warning": 0},
            "datacenter_count": len(vc_node.children),
            "esxi_host_count": sum(len(dc.children) for dc in vc_node.children),
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
        for dc_node in vc_node.children:
            dc_data = dc_node.data_source({}) if dc_node.data_source else {}
            datacenters_flat.append({
                "name": dc_node.title or dc_node.slug,
                "vcenter": vc_label,
                "report_url": f"{vc_node.slug}/{dc_node.slug}/{dc_node.slug}.html",
                "esxi_host_count": len(dc_node.children),
                "cluster_count": len((dc_data.get("clusters") or {})),
                # Internal reference resolved by render_tree after the
                # tree-state pass computes per-node alert rollups; the
                # value gets replaced with an ``ncs_alerts`` dict.
                "_node_ref": id(dc_node),
            })
            for esxi_node in dc_node.children:
                esxi_data = esxi_node.data_source({}).get("raw_esxi", {}).get("data", {}) if esxi_node.data_source else {}
                esxi_hosts_flat.append({
                    "name": esxi_node.title or esxi_node.slug,
                    "vcenter": vc_label,
                    "datacenter": dc_node.title or dc_node.slug,
                    "cluster": esxi_data.get("cluster") or "—",
                    "report_url": f"{vc_node.slug}/{dc_node.slug}/{esxi_node.slug}/{esxi_node.slug}.html",
                    "version": esxi_data.get("version", ""),
                    "overall_status": esxi_data.get("overall_status", "unknown"),
                    "_node_ref": id(esxi_node),
                })
                for vm in _as_list(esxi_data.get("virtual_machines")):
                    if isinstance(vm, dict):
                        virtual_machines_flat.append({
                            "name": vm.get("guest_name") or vm.get("name") or "",
                            "vcenter": vc_label,
                            "datacenter": dc_node.title or dc_node.slug,
                            "cluster": esxi_data.get("cluster") or "—",
                            "esxi_host": esxi_node.title or esxi_node.slug,
                            "esxi_host_url": (
                                f"{vc_node.slug}/{dc_node.slug}/{esxi_node.slug}/{esxi_node.slug}.html"
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
    """Populate datacenter → ESXi subtrees under a vCenter node.

    Clusters are intentionally not a navigation tier; each ESXi host's
    cluster membership surfaces as a column on the datacenter's host
    table via the esxi bundle's existing ``cluster`` field.
    """
    datastores = _as_list(vc_data.get("datastores"))
    dvswitches = _as_list(vc_data.get("dvswitches"))
    vm_bundle = vm_bundles.get(vc_host, {})
    all_vms = _as_list(vm_bundle.get("virtual_machines"))

    # Group clusters and datastores by datacenter so each DC page can
    # display its membership without scanning the full list.
    clusters_by_dc: dict[str, dict[str, dict[str, Any]]] = {}
    for cluster_name, cluster_data in clusters.items():
        if not isinstance(cluster_data, dict):
            continue
        dc_name = str(cluster_data.get("datacenter") or "").strip() or "unknown-datacenter"
        clusters_by_dc.setdefault(dc_name, {})[cluster_name] = cluster_data

    datastores_by_dc: dict[str, list[Any]] = {}
    for ds in datastores:
        if not isinstance(ds, dict):
            continue
        datastores_by_dc.setdefault(str(ds.get("datacenter", "")).strip(), []).append(ds)

    esxi_by_dc: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for esxi_host, esxi_data in esxi_bundles.items():
        if not isinstance(esxi_data, dict):
            continue
        dc_name = str(esxi_data.get("datacenter", "")).strip() or "unknown-datacenter"
        esxi_by_dc.setdefault(dc_name, []).append((esxi_host, esxi_data))

    vms_by_host: dict[str, list[dict[str, Any]]] = {}
    for vm in all_vms:
        if not isinstance(vm, dict):
            continue
        # The collector emits ``esxi_hostname`` (community.vmware naming);
        # accept either spelling for forward-compatibility.
        host_key = str(vm.get("esxi_hostname") or vm.get("esxi_host") or "").strip()
        vms_by_host.setdefault(host_key, []).append(vm)

    # Union of DCs from clusters_by_dc and esxi_by_dc so a DC with hosts
    # but no clusters still gets a node.
    for dc_name in sorted(set(clusters_by_dc) | set(esxi_by_dc)):
        dc_slug = slugify(dc_name)
        dc_clusters = clusters_by_dc.get(dc_name, {})
        dc_esxi = esxi_by_dc.get(dc_name, [])
        dc_data = {
            "datacenter_name": dc_name,
            "clusters": dc_clusters,
            "datastores": datastores_by_dc.get(dc_name, []),
            "dvswitches": dvswitches,
            "esxi_hosts": [
                {
                    "title": host,
                    "cluster": str(data.get("cluster", "")).strip() or "—",
                    "report_url": f"{slugify(host)}/{slugify(host)}.html",
                    "health": data.get("health") or data.get("overall_status") or "unknown",
                }
                for host, data in sorted(dc_esxi)
            ],
            "esxi_host_count": len(dc_esxi),
        }
        dc_node = vc_node.find_or_add_child(
            dc_slug,
            tier="datacenter",
            schema_name="datacenter",
            title=dc_name,
            data_source=_static_source(dc_data),
        )

        for esxi_host, esxi_data in sorted(dc_esxi):
            esxi_vms = vms_by_host.get(esxi_host, [])
            esxi_bundle = {
                "raw_esxi": {
                    "data": {**esxi_data, "virtual_machines": esxi_vms},
                    "metadata": {"host": esxi_host},
                },
            }
            dc_node.find_or_add_child(
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
