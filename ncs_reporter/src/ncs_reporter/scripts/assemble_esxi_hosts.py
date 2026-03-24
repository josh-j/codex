#!/usr/bin/env python3
"""Built-in script: assemble per-ESXi-host records from raw collection data.

stdin  — JSON: {"fields": {...}, "args": {}}
         fields.hosts_info contains host_facts, host_nics, host_services
         fields.clusters_info_results contains cluster→host mapping
stdout — JSON list of per-host dicts
exit 0 on success, 2 on unrecoverable error

Merges vmware_host_facts, vmware_host_vmnic_info, and
vmware_host_service_info results (Ansible loop output) into a flat
list of host records keyed by hostname.
"""

import json
import sys
from typing import Any


def _extract_loop_results(raw: Any) -> list[dict[str, Any]]:
    """Extract inner results from an Ansible loop register."""
    if isinstance(raw, dict):
        return raw.get("results", [])
    if isinstance(raw, list):
        return raw
    return []


def _build_cluster_map(clusters_results: Any) -> dict[str, dict[str, str]]:
    """Build hostname → {cluster, datacenter} from clusters_info loop results."""
    mapping: dict[str, dict[str, str]] = {}
    for dc_result in _extract_loop_results(clusters_results):
        if not isinstance(dc_result, dict):
            continue
        datacenter = dc_result.get("item", "")
        clusters = dc_result.get("clusters_info") or dc_result.get("clusters") or {}
        if not isinstance(clusters, dict):
            continue
        for cluster_name, cluster_data in clusters.items():
            if not isinstance(cluster_data, dict):
                continue
            for host in cluster_data.get("hosts", []):
                if isinstance(host, dict) and host.get("name"):
                    mapping[host["name"]] = {
                        "cluster": cluster_name,
                        "datacenter": datacenter,
                    }
    return mapping


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_host_facts(result: dict[str, Any]) -> dict[str, Any]:
    """Parse a single vmware_host_facts loop result into a host record."""
    hostname = result.get("item", "")
    facts = result.get("ansible_facts", {})
    if not isinstance(facts, dict):
        facts = {}

    mem_total = _safe_float(facts.get("ansible_memtotal_mb", 0))
    mem_free = _safe_float(facts.get("ansible_memfree_mb", 0))
    mem_used = mem_total - mem_free
    mem_pct = round((mem_used / mem_total) * 100, 1) if mem_total > 0 else 0.0

    # Processor info
    cpu_model = facts.get("ansible_processor", "")

    # Uptime
    uptime = _safe_int(facts.get("ansible_uptime", 0))

    # Datastores
    datastores = []
    for ds in facts.get("ansible_datastore", []):
        if isinstance(ds, dict):
            datastores.append({
                "name": ds.get("name", ""),
                "total": ds.get("total", ""),
                "free": ds.get("free", ""),
            })

    return {
        "name": hostname,
        "version": facts.get("ansible_distribution_version", ""),
        "build": facts.get("ansible_distribution_build", ""),
        "in_maintenance_mode": facts.get("ansible_in_maintenance_mode", False),
        "mem_mb_total": mem_total,
        "mem_mb_used": mem_used,
        "mem_used_pct": mem_pct,
        "cpu_model": cpu_model,
        "uptime_seconds": uptime,
        "os_type": facts.get("ansible_os_type", ""),
        "interfaces": facts.get("ansible_interfaces", []),
        "datastores": datastores,
        "overall_status": facts.get("ansible_host_connection_state", "unknown"),
        "connection_state": facts.get("ansible_host_connection_state", "unknown"),
    }


def _merge_nics(host: dict[str, Any], nic_result: dict[str, Any]) -> None:
    """Merge vmware_host_vmnic_info result into a host record."""
    hosts_nics = nic_result.get("hosts_vmnic_info", {})
    if not isinstance(hosts_nics, dict):
        return
    hostname = host["name"]
    host_nics = hosts_nics.get(hostname, {})
    if not isinstance(host_nics, dict):
        return

    nics = []
    for nic in host_nics.get("vmnic_details", []):
        if isinstance(nic, dict):
            nics.append({
                "device": nic.get("device", ""),
                "link_status": nic.get("status", "unknown"),
                "speed_mbps": _safe_int(nic.get("speed", 0)),
                "driver": nic.get("driver", ""),
                "switch": nic.get("vswitch", ""),
            })
    host["nics"] = nics


def _merge_services(host: dict[str, Any], svc_result: dict[str, Any]) -> None:
    """Merge vmware_host_service_info result into a host record."""
    hosts_svcs = svc_result.get("host_service_info", {})
    if not isinstance(hosts_svcs, dict):
        return
    hostname = host["name"]
    host_svcs = hosts_svcs.get(hostname, [])
    if not isinstance(host_svcs, list):
        return

    svc_map: dict[str, bool] = {}
    for svc in host_svcs:
        if isinstance(svc, dict):
            key = svc.get("key", "")
            running = svc.get("running", False)
            if key:
                svc_map[key] = running

    host["ssh_enabled"] = svc_map.get("TSM-SSH", False)
    host["shell_enabled"] = svc_map.get("TSM", False)
    host["ntp_running"] = svc_map.get("ntpd", False)
    host["services"] = svc_map


def assemble_hosts(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Main assembly: merge facts, NICs, services into per-host records."""
    hosts_info = fields.get("hosts_info", {})
    if not isinstance(hosts_info, dict):
        hosts_info = {}

    host_facts_results = _extract_loop_results(hosts_info.get("host_facts"))
    host_nics_results = _extract_loop_results(hosts_info.get("host_nics"))
    host_services_results = _extract_loop_results(hosts_info.get("host_services"))

    # Build cluster→host mapping
    cluster_map = _build_cluster_map(fields.get("clusters_info_results"))

    # Index NIC and service results by hostname
    nics_by_host: dict[str, dict[str, Any]] = {}
    for r in host_nics_results:
        if isinstance(r, dict) and r.get("item"):
            nics_by_host[r["item"]] = r

    svcs_by_host: dict[str, dict[str, Any]] = {}
    for r in host_services_results:
        if isinstance(r, dict) and r.get("item"):
            svcs_by_host[r["item"]] = r

    hosts: list[dict[str, Any]] = []
    for result in host_facts_results:
        if not isinstance(result, dict):
            continue
        if result.get("failed") or result.get("skipped"):
            continue

        host = _parse_host_facts(result)
        hostname = host["name"]

        # Add cluster/datacenter context
        ctx = cluster_map.get(hostname, {})
        host["cluster"] = ctx.get("cluster", "")
        host["datacenter"] = ctx.get("datacenter", "")

        # Merge NIC and service data
        if hostname in nics_by_host:
            _merge_nics(host, nics_by_host[hostname])
        if hostname in svcs_by_host:
            _merge_services(host, svcs_by_host[hostname])

        hosts.append(host)

    hosts.sort(key=lambda h: h.get("name", ""))
    return hosts


if __name__ == "__main__":
    try:
        input_data = json.load(sys.stdin)
        fields = input_data.get("fields", {})
        result = assemble_hosts(fields)
        print(json.dumps(result))
    except Exception as e:
        sys.stderr.write(f"Error: {e!s}\n")
        sys.exit(2)
