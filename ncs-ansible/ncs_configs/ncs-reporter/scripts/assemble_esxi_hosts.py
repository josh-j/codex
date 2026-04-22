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

from ncs_reporter.primitives import to_float, to_int


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


def _parse_host_facts(result: dict[str, Any]) -> dict[str, Any]:
    """Parse a single vmware_host_facts loop result into a host record."""
    hostname = result.get("item", "")
    facts = result.get("ansible_facts", {})
    if not isinstance(facts, dict):
        facts = {}

    mem_total = to_float(facts.get("ansible_memtotal_mb", 0))
    mem_free = to_float(facts.get("ansible_memfree_mb", 0))
    mem_used = mem_total - mem_free
    mem_pct = round((mem_used / mem_total) * 100, 1) if mem_total > 0 else 0.0

    # Processor info
    cpu_model = facts.get("ansible_processor", "")

    # Uptime
    uptime = to_int(facts.get("ansible_uptime", 0))

    # Datastores
    datastores = []
    for ds in facts.get("ansible_datastore", []):
        if isinstance(ds, dict):
            datastores.append({
                "name": ds.get("name", ""),
                "total": ds.get("total", ""),
                "free": ds.get("free", ""),
            })

    # CPU utilization: quickStats.overallCpuUsage / (numCpuCores * cpuMhz)
    cpu_cores = to_int(facts.get("ansible_processor_cores", 0))
    cpu_threads = to_int(facts.get("ansible_processor_vcpus", 0))
    # vmware_host_facts does not expose CPU usage MHz directly;
    # cpu_used_pct will be 0 unless enriched by additional collection.
    cpu_used_pct = to_float(facts.get("ansible_cpu_used_pct", 0.0))

    # VM count: not directly available from vmware_host_facts;
    # will be 0 unless enriched by additional per-host collection.
    vm_count = to_int(facts.get("ansible_vm_count", 0))

    return {
        "name": hostname,
        "version": facts.get("ansible_distribution_version", ""),
        "build": facts.get("ansible_distribution_build", ""),
        "in_maintenance_mode": facts.get("ansible_in_maintenance_mode", False),
        "mem_mb_total": mem_total,
        "mem_mb_used": mem_used,
        "mem_used_pct": mem_pct,
        "cpu_model": cpu_model,
        "cpu_cores": cpu_cores,
        "cpu_threads": cpu_threads,
        "cpu_used_pct": cpu_used_pct,
        "vm_count": vm_count,
        "uptime_seconds": uptime,
        "os_type": facts.get("ansible_os_type", ""),
        "interfaces": facts.get("ansible_interfaces", []),
        "datastores": datastores,
        "overall_status": facts.get("ansible_overall_status", "unknown"),
        "connection_state": facts.get("ansible_host_connection_state", "unknown"),
        "lockdown_mode": facts.get("ansible_lockdown_mode", "unknown"),
        "hardware_alerts": [],
        "nics": [],
        "vmknics": [],
    }


def _merge_nics(host: dict[str, Any], host_nics: dict[str, Any] | None) -> None:
    """Merge per-host vmnic info (already keyed to this host) into the record."""
    if not isinstance(host_nics, dict):
        return
    nics: list[dict[str, Any]] = []
    for nic in host_nics.get("vmnic_details", []):
        if isinstance(nic, dict):
            nics.append({
                "device": nic.get("device", ""),
                "link_status": nic.get("status", "unknown"),
                "speed_mbps": to_int(nic.get("speed", 0)),
                "driver": nic.get("driver", ""),
                "switch": nic.get("vswitch", ""),
            })
    host["nics"] = nics


def _merge_services(host: dict[str, Any], services: list[dict[str, Any]] | None) -> None:
    """Merge per-host service list (already keyed to this host) into the record."""
    if not isinstance(services, list):
        return
    svc_map: dict[str, bool] = {}
    for svc in services:
        if isinstance(svc, dict):
            key = svc.get("key", "")
            if key:
                svc_map[key] = svc.get("running", False)

    host["ssh_enabled"] = svc_map.get("TSM-SSH", False)
    host["shell_enabled"] = svc_map.get("TSM", False)
    host["ntp_running"] = svc_map.get("ntpd", False)
    host["services"] = svc_map


def assemble_hosts(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Main assembly: unpack per-host records from the folded bulk payload."""
    hosts_info = fields.get("hosts_info", {})
    if not isinstance(hosts_info, dict):
        hosts_info = {}

    host_records = _extract_loop_results(hosts_info.get("host_facts"))
    cluster_map = _build_cluster_map(fields.get("clusters_info_results"))

    hosts: list[dict[str, Any]] = []
    for record in host_records:
        if not isinstance(record, dict):
            continue
        if record.get("failed") or record.get("skipped"):
            continue

        host = _parse_host_facts(record)
        hostname = host["name"]

        ctx = cluster_map.get(hostname, {})
        host["cluster"] = ctx.get("cluster", "")
        host["datacenter"] = ctx.get("datacenter", "")

        _merge_nics(host, record.get("nics"))
        _merge_services(host, record.get("services"))

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
