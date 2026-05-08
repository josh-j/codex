"""Normalize vSphere API results into NCS graph/event payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ids import stable_id


GRAPH_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first(value: Any, *keys: str, default: Any = "") -> Any:
    cur = value
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        else:
            cur = getattr(cur, key, default)
    return default if cur is None else cur


def normalize_inventory(
    *,
    vcenter: str,
    datacenters: list[dict[str, Any]] | None = None,
    clusters: list[dict[str, Any]] | dict[str, Any] | None = None,
    hosts: list[dict[str, Any]] | None = None,
    vms: list[dict[str, Any]] | None = None,
    datastores: list[dict[str, Any]] | None = None,
    networks: list[dict[str, Any]] | None = None,
    tags: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    alarms: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Build a schema-versioned vSphere graph from raw-ish object lists."""
    vc_id = stable_id("vcenter", vcenter)
    datacenter_nodes = [_normalize_datacenter(vcenter, item) for item in as_list(datacenters)]
    cluster_nodes = _normalize_clusters(vcenter, clusters)
    host_nodes = [_normalize_host(vcenter, item) for item in as_list(hosts)]
    vm_nodes = [_normalize_vm(vcenter, item) for item in as_list(vms)]
    datastore_nodes = [_normalize_datastore(vcenter, item) for item in as_list(datastores)]
    network_nodes = [_normalize_network(vcenter, item) for item in as_list(networks)]
    tag_nodes = [_normalize_tag(vcenter, item) for item in as_list(tags)]
    snapshot_nodes = [_normalize_snapshot(vcenter, item) for item in as_list(snapshots)]

    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "kind": "vsphere_graph",
        "collected_at": collected_at or utc_now(),
        "vcenters": [{"id": vc_id, "name": vcenter, "hostname": vcenter}],
        "datacenters": datacenter_nodes,
        "clusters": cluster_nodes,
        "hosts": host_nodes,
        "vms": vm_nodes,
        "datastores": datastore_nodes,
        "networks": network_nodes,
        "tags": tag_nodes,
        "snapshots": snapshot_nodes,
        "alarms": as_list(alarms),
        "metadata": {
            "vcenter": vcenter,
            "counts": {
                "datacenters": len(datacenter_nodes),
                "clusters": len(cluster_nodes),
                "hosts": len(host_nodes),
                "vms": len(vm_nodes),
                "datastores": len(datastore_nodes),
                "networks": len(network_nodes),
                "tags": len(tag_nodes),
                "snapshots": len(snapshot_nodes),
                "alarms": len(as_list(alarms)),
            },
        },
        "errors": as_list(errors),
    }


def normalize_events(
    *,
    vcenter: str,
    alarms: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    window_hours: int = 24,
    limit: int = 500,
    collected_at: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_rows = [_normalize_event_row(vcenter, "task", row) for row in as_list(tasks)]
    event_rows = [_normalize_event_row(vcenter, "event", row) for row in as_list(events)]
    alarm_rows = [_normalize_event_row(vcenter, "alarm", row) for row in as_list(alarms)]
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "kind": "vsphere_events",
        "collected_at": collected_at or utc_now(),
        "vcenter": vcenter,
        "window_hours": window_hours,
        "limit": limit,
        "active_alarms": alarm_rows[:limit],
        "tasks": task_rows[:limit],
        "events": event_rows[:limit],
        "errors": as_list(errors),
    }


def operation_event(
    *,
    operation_id: str,
    task_id: str,
    tier: int,
    target_type: str,
    requested_targets: list[Any],
    resolved_targets: list[Any],
    started_at: str,
    ended_at: str,
    result: str,
    changed: bool,
    read_only: bool,
    before: Any = None,
    after: Any = None,
    errors: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "operation_event",
        "id": operation_id,
        "task_id": task_id,
        "tier": tier,
        "target_type": target_type,
        "read_only": read_only,
        "requested_targets": requested_targets,
        "resolved_targets": resolved_targets,
        "started_at": started_at,
        "ended_at": ended_at,
        "result": result,
        "changed": changed,
        "before": before,
        "after": after,
        "errors": as_list(errors),
    }


def _normalize_datacenter(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "name", default=first(item, "datacenter", default="")) or "")
    return {"id": stable_id("datacenter", vcenter, name), "vcenter_id": stable_id("vcenter", vcenter), "name": name}


def _normalize_clusters(vcenter: str, clusters: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if isinstance(clusters, dict):
        iterable = [{"name": key, **as_dict(value)} for key, value in clusters.items()]
    else:
        iterable = as_list(clusters)
    out = []
    for item in iterable:
        name = str(first(item, "name", default=first(item, "cluster", default="")) or "")
        dc = str(first(item, "datacenter", default="") or "")
        out.append({
            "id": stable_id("cluster", vcenter, dc, name),
            "vcenter_id": stable_id("vcenter", vcenter),
            "datacenter_id": stable_id("datacenter", vcenter, dc) if dc else "",
            "name": name,
            "datacenter": dc,
            "host_ids": [stable_id("host", vcenter, h.get("name", h)) for h in as_list(first(item, "hosts", default=[]))],
            "ha_enabled": bool(first(item, "ha_enabled", default=False)),
            "drs_enabled": bool(first(item, "drs_enabled", default=False)),
        })
    return out


def _normalize_host(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "name", default=first(item, "hostname", default=first(item, "item", default=""))) or "")
    return {
        "id": stable_id("host", vcenter, name),
        "vcenter_id": stable_id("vcenter", vcenter),
        "name": name,
        "datacenter": str(first(item, "datacenter", default="") or ""),
        "cluster": str(first(item, "cluster", default="") or ""),
        "connection_state": str(first(item, "connection_state", default=first(item, "runtime", "connectionState", default="unknown")) or "unknown"),
        "overall_status": str(first(item, "overall_status", default=first(item, "summary", "overallStatus", default="unknown")) or "unknown"),
        "maintenance_mode": bool(first(item, "in_maintenance_mode", default=first(item, "runtime", "inMaintenanceMode", default=False))),
    }


def _normalize_vm(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "guest_name", default=first(item, "name", default="")) or "")
    host = str(first(item, "esxi_hostname", default=first(item, "host", default="")) or "")
    return {
        "id": stable_id("vm", vcenter, name),
        "vcenter_id": stable_id("vcenter", vcenter),
        "name": name,
        "host_id": stable_id("host", vcenter, host) if host else "",
        "host": host,
        "datacenter": str(first(item, "datacenter", default="") or ""),
        "cluster": str(first(item, "cluster", default="") or ""),
        "power_state": str(first(item, "power_state", default="") or ""),
        "guest_os": str(first(item, "guest_fullname", default=first(item, "guest_os", default="")) or ""),
        "ip_address": str(first(item, "ip_address", default="") or ""),
        "tags": as_list(first(item, "tags", default=[])),
        "custom_attributes": first(item, "customvalues", default=first(item, "attributes", default={})),
    }


def _normalize_datastore(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "name", default="") or "")
    return {
        "id": stable_id("datastore", vcenter, name),
        "vcenter_id": stable_id("vcenter", vcenter),
        "name": name,
        "type": str(first(item, "type", default="") or ""),
        "capacity_bytes": int(first(item, "capacity", default=0) or 0),
        "free_bytes": int(first(item, "freeSpace", default=first(item, "free_space", default=0)) or 0),
    }


def _normalize_network(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "name", default=first(item, "portgroup_name", default="")) or "")
    return {"id": stable_id("network", vcenter, name), "vcenter_id": stable_id("vcenter", vcenter), "name": name}


def _normalize_tag(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "tag_name", default=first(item, "name", default="")) or "")
    return {"id": stable_id("tag", vcenter, name), "vcenter_id": stable_id("vcenter", vcenter), "name": name, "category": first(item, "category_name", default="")}


def _normalize_snapshot(vcenter: str, item: dict[str, Any]) -> dict[str, Any]:
    name = str(first(item, "name", default=first(item, "snapshot_name", default="")) or "")
    vm_name = str(first(item, "vm_name", default=first(item, "guest_name", default="")) or "")
    return {
        "id": stable_id("snapshot", vcenter, vm_name, name),
        "vcenter_id": stable_id("vcenter", vcenter),
        "vm_id": stable_id("vm", vcenter, vm_name) if vm_name else "",
        "vm_name": vm_name,
        "name": name,
        "created": str(first(item, "creation_time", default=first(item, "created", default="")) or ""),
        "description": str(first(item, "description", default="") or ""),
    }


def _normalize_event_row(vcenter: str, kind: str, row: dict[str, Any]) -> dict[str, Any]:
    key = first(row, "key", default=first(row, "id", default=""))
    created = str(first(row, "createdTime", default=first(row, "time", default=first(row, "created", default=""))) or "")
    message = str(first(row, "fullFormattedMessage", default=first(row, "message", default=first(row, "description", default=""))) or "")
    return {
        "id": stable_id(kind, vcenter, key or created or message[:80]),
        "vcenter": vcenter,
        "kind": kind,
        "time": created,
        "entity": str(first(row, "entity", "name", default=first(row, "entity", default="")) or ""),
        "user": str(first(row, "userName", default=first(row, "user", default="")) or ""),
        "message": message,
        "status": str(first(row, "status", default=first(row, "state", default="")) or ""),
        "severity": str(first(row, "severity", default="info") or "info"),
    }

