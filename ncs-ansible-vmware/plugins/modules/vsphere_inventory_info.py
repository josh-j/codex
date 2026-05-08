#!/usr/bin/python
"""Collect a normalized vSphere inventory graph."""

from __future__ import annotations

import ssl
import sys
from typing import Any

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.internal.vmware.plugins.module_utils.vsphere.normalize import normalize_inventory

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim

    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False


DOCUMENTATION = r"""
---
module: vsphere_inventory_info
short_description: Collect normalized vSphere inventory graph
description:
  - Collects vCenter inventory into a schema-versioned C(vsphere_graph) payload.
options:
  hostname:
    type: str
    required: true
  username:
    type: str
    required: true
  password:
    type: str
    required: true
    no_log: true
  validate_certs:
    type: bool
    default: false
  host_alias_map:
    description:
      - Map of vCenter-native ESXi host name (often an IP) to a preferred
        name (e.g. an Ansible inventory hostname). Applied to host entries
        in the emitted graph. Pass an empty dict to leave names as vCenter
        reports them.
    type: dict
    default: {}
author:
  - NCS
"""

RETURN = r"""
vsphere_graph:
  description: Normalized vSphere graph.
  returned: always
  type: dict
"""


def _children(content: Any, vimtype: list[Any]) -> list[Any]:
    view = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _name(obj: Any) -> str:
    return str(getattr(obj, "name", "") or "")


def _alias(name: str, host_alias_map: dict[str, str]) -> str:
    """Map a vCenter-native host name (often an IP) to the operator-friendly
    inventory hostname when the playbook passes a ``host_alias_map``. Falls
    through to the original name if no mapping exists."""
    return host_alias_map.get(name, name)


def _parent_name(obj: Any, cls: Any) -> str:
    cur = getattr(obj, "parent", None)
    while cur is not None:
        if isinstance(cur, cls):
            return _name(cur)
        cur = getattr(cur, "parent", None)
    return ""


def _collect(content: Any, hostname: str, host_alias_map: dict[str, str]) -> dict[str, Any]:
    datacenters = [{"name": _name(dc)} for dc in _children(content, [vim.Datacenter])]

    clusters = []
    for cluster in _children(content, [vim.ClusterComputeResource]):
        clusters.append({
            "name": _name(cluster),
            "datacenter": _parent_name(cluster, vim.Datacenter),
            "hosts": [
                {"name": _alias(_name(h), host_alias_map)}
                for h in list(getattr(cluster, "host", []) or [])
            ],
            "ha_enabled": bool(getattr(getattr(cluster, "configurationEx", None), "dasConfig", None) and getattr(cluster.configurationEx.dasConfig, "enabled", False)),
            "drs_enabled": bool(getattr(getattr(cluster, "configurationEx", None), "drsConfig", None) and getattr(cluster.configurationEx.drsConfig, "enabled", False)),
        })

    hosts = []
    for host in _children(content, [vim.HostSystem]):
        summary = getattr(host, "summary", None)
        runtime = getattr(host, "runtime", None)
        hosts.append({
            "name": _alias(_name(host), host_alias_map),
            "datacenter": _parent_name(host, vim.Datacenter),
            "cluster": _parent_name(host, vim.ClusterComputeResource),
            "connection_state": str(getattr(runtime, "connectionState", "unknown")),
            "overall_status": str(getattr(summary, "overallStatus", "unknown")),
            "in_maintenance_mode": bool(getattr(runtime, "inMaintenanceMode", False)),
        })

    vms = []
    for vm in _children(content, [vim.VirtualMachine]):
        summary = getattr(vm, "summary", None)
        config = getattr(summary, "config", None)
        guest = getattr(summary, "guest", None)
        runtime = getattr(summary, "runtime", None)
        host = getattr(runtime, "host", None)
        vms.append({
            "name": _name(vm),
            "guest_name": _name(vm),
            "guest_fullname": getattr(config, "guestFullName", "") or "",
            "power_state": str(getattr(runtime, "powerState", "") or ""),
            "ip_address": getattr(guest, "ipAddress", "") or "",
            "esxi_hostname": _alias(_name(host), host_alias_map) if host else "",
            "datacenter": _parent_name(vm, vim.Datacenter),
            "cluster": _parent_name(host, vim.ClusterComputeResource) if host else "",
        })

    datastores = []
    for ds in _children(content, [vim.Datastore]):
        summary = getattr(ds, "summary", None)
        datastores.append({
            "name": _name(ds),
            "type": getattr(summary, "type", "") or "",
            "capacity": int(getattr(summary, "capacity", 0) or 0),
            "freeSpace": int(getattr(summary, "freeSpace", 0) or 0),
        })

    networks = [{"name": _name(net)} for net in _children(content, [vim.Network])]
    snapshots = []
    for vm in _children(content, [vim.VirtualMachine]):
        _append_snapshots(snapshots, _name(vm), getattr(getattr(vm, "snapshot", None), "rootSnapshotList", []) or [])

    alarms = []
    for state in getattr(content.rootFolder, "triggeredAlarmState", None) or []:
        acknowledged = bool(getattr(state, "acknowledged", False))
        status = str(getattr(state, "overallStatus", "gray")).lower()
        if acknowledged or status in {"green", "gray"}:
            continue
        alarm = getattr(state, "alarm", None)
        info = getattr(alarm, "info", None) if alarm else None
        entity = getattr(state, "entity", None)
        alarms.append({
            "key": getattr(alarm, "_moId", "") if alarm else "",
            "message": getattr(info, "name", "Unknown alarm"),
            "description": getattr(info, "description", "") or "",
            "entity": getattr(entity, "name", "") if entity else "",
            "status": status,
            "severity": "critical" if status == "red" else "warning" if status == "yellow" else "info",
            "time": str(getattr(state, "time", "") or ""),
        })

    return normalize_inventory(
        vcenter=hostname,
        datacenters=datacenters,
        clusters=clusters,
        hosts=hosts,
        vms=vms,
        datastores=datastores,
        networks=networks,
        snapshots=snapshots,
        alarms=alarms,
    )


def _append_snapshots(rows: list[dict[str, Any]], vm_name: str, tree: list[Any]) -> None:
    for node in tree or []:
        rows.append({
            "vm_name": vm_name,
            "name": getattr(node, "name", "") or "",
            "description": getattr(node, "description", "") or "",
            "creation_time": str(getattr(node, "createTime", "") or ""),
        })
        _append_snapshots(rows, vm_name, list(getattr(node, "childSnapshotList", []) or []))


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "hostname": {"type": "str", "required": True},
            "username": {"type": "str", "required": True},
            "password": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": False},
            # vCenter-native-name → preferred-name (e.g. inventory hostname).
            # Lab vCenters often register ESXi hosts by IP; the playbook
            # builds this map from ``groups['esxi_hosts']`` so the emitted
            # graph keys hosts by ``esxi01.maas-lab`` rather than the IP.
            "host_alias_map": {"type": "dict", "default": {}},
        },
        supports_check_mode=True,
    )
    result: dict[str, Any] = {"changed": False, "python": sys.executable, "vsphere_graph": {}}
    if not HAS_PYVMOMI:
        module.fail_json(msg="pyVmomi is required for vsphere_inventory_info", **result)

    context = ssl.create_default_context() if module.params["validate_certs"] else ssl._create_unverified_context()
    si = None
    try:
        si = SmartConnect(
            host=module.params["hostname"],
            user=module.params["username"],
            pwd=module.params["password"],
            sslContext=context,
        )
        result["vsphere_graph"] = _collect(
            si.RetrieveContent(),
            module.params["hostname"],
            module.params["host_alias_map"] or {},
        )
        module.exit_json(**result)
    except Exception as exc:
        result["vsphere_graph"] = normalize_inventory(
            vcenter=module.params["hostname"],
            errors=[{"source": "vsphere_inventory_info", "message": str(exc)}],
        )
        module.fail_json(msg=str(exc), **result)
    finally:
        if si is not None:
            Disconnect(si)


if __name__ == "__main__":
    run_module()
