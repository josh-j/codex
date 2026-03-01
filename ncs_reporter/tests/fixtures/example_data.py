"""Factory functions for realistic example data bundles.

Each factory returns a dict matching the raw bundle structure that
normalize_from_schema / build_generic_node_view receive: the detection
key at the top level, then the ncs_collector envelope beneath it
(metadata + data).

Module RETURN samples are used as structural templates so that field names
and types are derived from the real modules rather than maintained manually.
Any module schema change is one import refresh away.

unhealthy=True (default) → picks values that fire alerts so generated
example reports look interesting.
unhealthy=False → values that clear all alert conditions.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fixtures._static_samples import (
    APPLIANCE_BASE as _APPLIANCE_BASE,
    DS_BASE as _DS_BASE,
    VM_BASE as _VM_BASE,
    WIN_SVC_BASE as _WIN_SVC_BASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _days_ago_iso(days: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# Module RETURN sample bases (see fixtures/_static_samples.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ds(name: str, capacity: int, free: int, ds_type: str = "VMFS", **extra: object) -> dict:
    """Build a datastore dict from the module RETURN sample, overriding key fields.

    The sample has accessible=False (a degraded example); we default to True so
    callers only need to set accessible=False when intentionally testing inaccessibility.
    """
    ds = copy.deepcopy(_DS_BASE)
    ds.update({"name": name, "type": ds_type, "capacity": capacity, "freeSpace": free, "accessible": True})
    ds.update(extra)
    return ds


def _make_vm(
    guest_name: str,
    power_state: str,
    tools_status: str,
    ip: str,
    moid: str,
    uuid: str,
    **extra: Any,
) -> dict:
    """Build a VM dict from the module RETURN sample, overriding key fields."""
    vm = copy.deepcopy(_VM_BASE)
    vm.update(
        {
            "guest_name": guest_name,
            "power_state": power_state,
            "tools_status": tools_status,
            "ip_address": ip,
            "moid": moid,
            "uuid": uuid,
            "instance_uuid": uuid.replace("-", "")[:32],
            "resource_pool": None,
            "num_cpu": extra.get("num_cpu", 2),
            "memory_mb": extra.get("memory_mb", 4096),
            "tags": extra.get(
                "tags",
                [
                    {"category_name": "Owner", "name": "Platform Team", "description": "Shared Platform Resources"},
                    {
                        "category_name": "Backup Schedule",
                        "name": "Daily-Prod",
                        "description": "Standard Daily Retention",
                    },
                ],
            ),
            "attributes": extra.get(
                "attributes",
                {
                    "Owner Email": "platform-alerts@corp.local",
                    "Owner Name": "Platform Team",
                    "Last Dell PowerProtect Backup": _days_ago_iso(0.5),
                },
            ),
        }
    )
    # Remove keys from extra that we've already handled or don't want in top-level update
    for k in ["num_cpu", "memory_mb", "tags", "attributes"]:
        extra.pop(k, None)
    vm.update(extra)
    return vm


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------


def make_linux_bundle(hostname: str, ip: str, *, unhealthy: bool = True, variety: bool = False) -> dict:
    """Build a realistic ubuntu_raw_discovery bundle.

    unhealthy=True triggers: memory_critical, services_failed, disk_critical,
    disk_warning, reboot_pending, pending_updates, world_writable_files.
    variety=True triggers: memory_warning (90% used), uptime_violation (200 days).
    unhealthy=False → healthy host, no alerts.

    ansible.builtin.command and ansible.builtin.stat RETURN structures are used
    as documentation anchors for the stdout_lines/rc and stat/exists shapes.
    """
    if unhealthy:
        memfree_mb = 328  # 99% of 32768 used → CRITICAL
        uptime_seconds = 1468800  # 17 days
        failed_svc_lines: list[str] = [
            "  ssh.service      loaded failed failed  OpenBSD Secure Shell server",
            "  rsyslog.service  loaded failed failed  System Logging Service",
        ]
        apt_lines: list[str] = [
            "Reading package lists...",
            "Building dependency tree...",
            "12 upgraded, 3 newly installed, 0 to remove and 0 not upgraded.",
        ]
        reboot_exists = True
        world_writable: list[str] = [
            "/var/log/app/runtime.log",
            "/var/spool/custom/queue",
            "/var/tmp/legacy-socket",
        ]
        mounts: list[dict] = [
            # 47% used — OK
            {
                "mount": "/",
                "device": "/dev/sda1",
                "fstype": "ext4",
                "size_total": 107374182400,
                "size_available": 56371445760,
            },
            # 96% used — CRITICAL
            {
                "mount": "/var",
                "device": "/dev/sda2",
                "fstype": "ext4",
                "size_total": 214748364800,
                "size_available": 8589934592,
            },
            # 82% used — WARNING
            {
                "mount": "/opt",
                "device": "/dev/sda3",
                "fstype": "ext4",
                "size_total": 53687091200,
                "size_available": 9663676416,
            },
            # tmpfs — filtered out by disk_inventory.py
            {
                "mount": "/tmp",
                "device": "tmpfs",
                "fstype": "tmpfs",
                "size_total": 8589934592,
                "size_available": 8052867072,
            },
            # 50% used — OK
            {
                "mount": "/boot",
                "device": "/dev/sda4",
                "fstype": "ext4",
                "size_total": 1073741824,
                "size_available": 536870912,
            },
        ]
        load_avg = 3.8
    elif variety:
        # Fires: memory_warning (90% used), uptime_violation (200 days)
        memfree_mb = 3276  # ~90% of 32768 used → WARNING (not critical)
        uptime_seconds = 17280000  # 200 days → uptime_violation
        failed_svc_lines = []
        apt_lines = ["0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."]
        reboot_exists = False
        world_writable = []
        mounts = [
            {
                "mount": "/",
                "device": "/dev/sda1",
                "fstype": "ext4",
                "size_total": 107374182400,
                "size_available": 64424509440,
            },
            {
                "mount": "/var",
                "device": "/dev/sda2",
                "fstype": "ext4",
                "size_total": 214748364800,
                "size_available": 150000000000,
            },
        ]
        load_avg = 1.2
    else:
        memfree_mb = 16000
        uptime_seconds = 1468800  # 17 days
        failed_svc_lines = []
        apt_lines = ["0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."]
        reboot_exists = False
        world_writable = []
        mounts = [
            {
                "mount": "/",
                "device": "/dev/sda1",
                "fstype": "ext4",
                "size_total": 107374182400,
                "size_available": 75000000000,
            },
            {
                "mount": "/var",
                "device": "/dev/sda2",
                "fstype": "ext4",
                "size_total": 214748364800,
                "size_available": 150000000000,
            },
        ]
        load_avg = 0.4

    # ansible.builtin.command shape: {stdout_lines, rc, ...}
    # ansible.builtin.stat shape: {stat: {exists, path, ...}}
    return {
        "ubuntu_raw_discovery": {
            "metadata": {
                "host": hostname,
                "raw_type": "discovery",
                "timestamp": _now_iso(),
                "engine": "ncs_collector_callback",
            },
            "data": {
                # ansible.builtin.setup — ansible_facts keys stored without ansible_ prefix
                "ansible_facts": {
                    "hostname": hostname,
                    "default_ipv4": {"address": ip},
                    "kernel": "6.8.0-48-generic",
                    "os_family": "Debian",
                    "distribution": "Ubuntu",
                    "distribution_version": "24.04",
                    "uptime_seconds": uptime_seconds,
                    "loadavg": {"15m": load_avg},
                    "memtotal_mb": 32768,
                    "memfree_mb": memfree_mb,
                    "swaptotal_mb": 8192,
                    "swapfree_mb": 7372,
                    "mounts": mounts,
                    "getent_passwd": {
                        "root": ["x", "0", "0", "root", "/root", "/bin/bash"],
                        "ubuntu": ["x", "1000", "1000", "Ubuntu", "/home/ubuntu", "/bin/bash"],
                        "syslog": ["x", "104", "110", "", "/home/syslog", "/usr/sbin/nologin"],
                        "deploy": ["x", "1001", "1001", "deploy", "/home/deploy", "/bin/bash"],
                    },
                    "date_time": {"epoch": str(int(time.time()))},
                },
                # ansible.builtin.command: {stdout_lines, rc}
                "failed_services": {
                    "stdout_lines": failed_svc_lines,
                    "rc": 0,
                },
                "apt_simulate": {
                    "stdout_lines": apt_lines,
                    "rc": 0,
                },
                # ansible.builtin.stat: {stat: {exists, path}}
                "reboot_stat": {
                    "stat": {"exists": reboot_exists, "path": "/var/run/reboot-required"},
                },
                "shadow_raw": {
                    "stdout_lines": [
                        "root:!:19700:0:99999:7:::",
                        "ubuntu:$6$rounds=5000$salt$hash:19600:0:99999:7:::",
                        "syslog:*:18000:0:99999:7:::",
                        "deploy:$6$rounds=5000$salt$hash2:19620:0:99999:7:::",
                    ],
                    "rc": 0,
                },
                "sshd_raw": {
                    "stdout_lines": [
                        "port 22",
                        "addressfamily any",
                        "listenaddress 0.0.0.0",
                        "permitemptypasswords no",
                        "permituserenvironment no",
                        "passwordauthentication no",
                        "permitrootlogin no",
                        "usepam yes",
                        "x11forwarding no",
                        "maxauthtries 4",
                        "clientaliveinterval 600",
                        "clientalivecountmax 0",
                        "banner /etc/issue.net",
                        "logingracetime 60",
                        "strictmodes yes",
                        "pubkeyauthentication yes",
                    ],
                    "rc": 0,
                },
                "world_writable": {
                    "stdout_lines": world_writable,
                    "rc": 0,
                },
                "file_stats": {
                    "results": [
                        {
                            "item": "/etc/shadow",
                            "stat": {"exists": True, "mode": "0640", "pw_name": "root", "gr_name": "shadow"},
                        },
                        {
                            "item": "/etc/passwd",
                            "stat": {"exists": True, "mode": "0644", "pw_name": "root", "gr_name": "root"},
                        },
                        {
                            "item": "/etc/ssh/sshd_config",
                            "stat": {"exists": True, "mode": "0600", "pw_name": "root", "gr_name": "root"},
                        },
                    ],
                },
            },
        }
    }


# ---------------------------------------------------------------------------
# VMware vCenter
# ---------------------------------------------------------------------------


def make_vcenter_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    """Build a realistic vmware_raw_vcenter bundle.

    Structural templates come from actual module RETURN samples:
    - appliance_health_info: vmware.vmware.appliance_info
    - appliance_backup_info: vmware.vmware.vcsa_backup_schedule_info
    - datastores_info: community.vmware.vmware_datastore_info
    - vms_info: community.vmware.vmware_vm_info
    - alarms_info: internal.vmware.vmware_triggered_alarms_info → {alarms, count, python}

    unhealthy=True triggers ALL vCenter alert types (mutually exclusive pairs noted):
      appliance_health_yellow, backup_schedule_disabled, ssh_enabled, shell_enabled,
      datastore_critical_space, datastore_warning_space, datastore_inaccessible,
      active_critical_alarms, active_warning_alarms,
      vm_tools_not_running, vm_tools_not_installed,
      snapshots_present, aged_snapshots.
    Note: no_backup_schedule (count=0) and backup_schedule_disabled (disabled exists)
    are mutually exclusive — unhealthy fires backup_schedule_disabled.
    unhealthy=False → healthy environment, no alerts.
    """
    if unhealthy:
        health = {
            "cpu": "green",
            "database": "green",
            "memory": "yellow",
            "overall": "yellow",
            "storage": "green",
            "swap": "green",
        }
        # no_backup_schedule: empty list fires it
        # backup_schedule_disabled: a disabled schedule ALSO fires when present
        # Both fire simultaneously — a disabled schedule AND no enabled one
        backup_schedules: list[dict] = [
            {
                "name": "default",
                "enabled": False,  # backup_schedule_disabled CRITICAL
                "fast_backup": False,
                "location": "nfs://10.10.10.10:/nfs/backup/vcenter/",
                "location_user": "backupuser",
                "includes_stats_events_and_tasks": True,
                "includes_supervisors_control_plane": False,
                "retain_count": 3,
                "schedule": {
                    "days_of_week": ["SATURDAY"],
                    "hour": 2,
                    "minute": 0,
                },
            }
        ]
        ssh_enabled = True  # ssh_enabled WARNING
        shell_enabled_str = "True"  # shell_enabled WARNING (str from real module)
        datastores: list[dict] = [
            # 30% free — OK
            _make_ds(
                "PROD-VMFS-SSD-01",
                10995116277760,
                3298534883328,
                maintenanceMode="normal",
                multipleHostAccess=True,
                provisioned=8796093022208,
                uncommitted=1099511627776,
            ),
            # 7% free → datastore_critical_space
            _make_ds(
                "PROD-VMFS-SSD-02",
                10995116277760,
                769727561728,
                maintenanceMode="normal",
                multipleHostAccess=True,
                provisioned=10500000000000,
                uncommitted=274877906944,
            ),
            # 13% free → datastore_warning_space
            _make_ds(
                "PROD-NFS-01",
                21990232555520,
                2857749006336,
                ds_type="NFS",
                maintenanceMode="normal",
                multipleHostAccess=True,
                provisioned=20000000000000,
                uncommitted=0,
            ),
            # 35% free — OK
            _make_ds(
                "PROD-NFS-BACKUP",
                21990232555520,
                7696581394432,
                ds_type="NFS",
                maintenanceMode="normal",
                multipleHostAccess=True,
                provisioned=15000000000000,
                uncommitted=0,
            ),
            # 50% free — OK
            _make_ds(
                "DR-VMFS-01",
                5497558138880,
                2748779069440,
                maintenanceMode="normal",
                multipleHostAccess=False,
                provisioned=2500000000000,
                uncommitted=248779069440,
            ),
            # inaccessible → datastore_inaccessible CRITICAL
            _make_ds(
                "CRASH-NFS-01",
                5497558138880,
                0,
                ds_type="NFS",
                accessible=False,
                maintenanceMode="normal",
                multipleHostAccess=False,
                provisioned=0,
                uncommitted=0,
            ),
        ]
        vms: list[dict] = [
            # clean
            _make_vm(
                "web-prod-01",
                "poweredOn",
                "toolsOk",
                "10.10.20.45",
                "vm-101",
                "4207072c-edd8-3bd5-64dc-903fd3a0db01",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi01.corp.local",
            ),
            # toolsNotRunning + poweredOn → vm_tools_not_running
            _make_vm(
                "db-prod-01",
                "poweredOn",
                "toolsNotRunning",
                "10.10.20.46",
                "vm-102",
                "4207072c-edd8-3bd5-64dc-903fd3a0db02",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi02.corp.local",
            ),
            # toolsNotInstalled + poweredOn → vm_tools_not_installed
            _make_vm(
                "monitoring-01",
                "poweredOn",
                "toolsNotInstalled",
                "10.10.20.47",
                "vm-103",
                "4207072c-edd8-3bd5-64dc-903fd3a0db03",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi01.corp.local",
            ),
            # clean
            _make_vm(
                "app-prod-01",
                "poweredOn",
                "toolsOk",
                "10.10.20.48",
                "vm-105",
                "4207072c-edd8-3bd5-64dc-903fd3a0db05",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi01.corp.local",
            ),
            # powered off for DR — tools issues on poweredOff don't alert
            _make_vm(
                "dr-vm-01",
                "poweredOff",
                "toolsOk",
                "",
                "vm-104",
                "4207072c-edd8-3bd5-64dc-903fd3a0db04",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi03.corp.local",
            ),
        ]
        # All 3 snapshots > 7 days old → aged_snapshot_count = 3
        snapshots: list[dict] = [
            {
                "vm_name": "test-vm-01",
                "folder": "/DC-Production/vm",
                "name": "pre-upgrade-snapshot",
                "description": "Before kernel upgrade",
                "creation_time": _days_ago_iso(27),
                "state": "poweredOff",
                "id": 12,
                "quiesced": False,
            },
            {
                "vm_name": "app-prod-01",
                "folder": "/DC-Production/vm",
                "name": "pre-patch-jan",
                "description": "Pre-January patching window",
                "creation_time": _days_ago_iso(44),
                "state": "poweredOn",
                "id": 7,
                "quiesced": False,
            },
            {
                "vm_name": "app-prod-01",
                "folder": "/DC-Production/vm",
                "name": "rollback-checkpoint",
                "description": "Emergency rollback point",
                "creation_time": _days_ago_iso(8),
                "state": "poweredOn",
                "id": 15,
                "quiesced": True,
            },
        ]
        alarms: list[dict] = [
            {
                "alarm_name": "Host CPU Usage",
                "description": "CPU on Prod-ESXi-03 exceeded 90% for 15 min",
                "entity": "Prod-ESXi-03",
                "entity_type": "HostSystem",
                "status": "red",
                "severity": "critical",
                "time": _days_ago_iso(0.25),
                "acknowledged": False,
            },
            {
                "alarm_name": "Datastore Free Space",
                "description": "PROD-VMFS-SSD-02 has less than 10% free space",
                "entity": "PROD-VMFS-SSD-02",
                "entity_type": "Datastore",
                "status": "yellow",
                "severity": "warning",
                "time": _days_ago_iso(1),
                "acknowledged": False,
            },
        ]
    else:
        health = {
            "cpu": "green",
            "database": "green",
            "memory": "green",
            "overall": "green",
            "storage": "green",
            "swap": "green",
        }
        ssh_enabled = False
        shell_enabled_str = "False"
        # Use module RETURN sample structure for healthy schedule
        backup_schedules = [
            {
                "name": "default",
                "enabled": True,
                "fast_backup": False,
                "location": "nfs://10.10.10.10:/nfs/backup/vcenter/",
                "location_user": "backupuser",
                "includes_stats_events_and_tasks": True,
                "includes_supervisors_control_plane": False,
                "retain_count": 3,
                "schedule": {
                    "days_of_week": ["SATURDAY"],
                    "hour": 2,
                    "minute": 0,
                },
            }
        ]
        datastores = [
            _make_ds(
                "PROD-VMFS-SSD-01", 10995116277760, 5497558138880, maintenanceMode="normal", multipleHostAccess=True
            ),
        ]
        vms = [
            _make_vm(
                "web-prod-01",
                "poweredOn",
                "toolsOk",
                "10.10.20.45",
                "vm-101",
                "4207072c-edd8-3bd5-64dc-903fd3a0db01",
                datacenter="DC-Production",
                cluster="Prod-Cluster-01",
                esxi_hostname="esxi01.corp.local",
            ),
        ]
        snapshots = []
        alarms = []

    # Build appliance_health_info from module RETURN sample, overriding scenario values.
    # appliance_info RETURN sample: {"appliance": {access, summary, time, ...}}
    appliance_health_info = copy.deepcopy(_APPLIANCE_BASE)
    _appl = appliance_health_info["appliance"]
    _appl["summary"]["health"] = health
    _appl["summary"]["uptime"] = "2592000.0"  # STRING — real module returns str
    _appl["summary"]["hostname"] = [f"{hostname}.corp.local"]
    _appl["summary"]["build_number"] = "24022515"
    _appl["summary"]["version"] = "8.0.3.00300"
    _appl["summary"]["product"] = "VMware vCenter Server"
    _appl["access"]["ssh"] = ssh_enabled
    _appl["access"]["shell"]["enabled"] = shell_enabled_str  # STRING — real module returns str
    _appl["access"]["shell"]["timeout"] = "0"
    _appl["time"]["time_sync"]["mode"] = "NTP"
    _appl["time"]["time_sync"]["servers"] = ["time.google.com"]

    return {
        "vmware_raw_vcenter": {
            "metadata": {
                "host": hostname,
                "raw_type": "vcenter",
                "timestamp": _now_iso(),
                "engine": "ncs_collector_callback",
            },
            "data": {
                "appliance_health_info": appliance_health_info,
                "appliance_backup_info": {"schedules": backup_schedules},
                "datacenters_info": {
                    # vmware.vmware_rest.vcenter_datacenter_info returns datacenter_info list
                    "datacenter_info": [
                        {
                            "name": "DC-Production",
                            "moid": "datacenter-1",
                            "config_status": "green",
                            "overall_status": "green",
                        },
                        {"name": "DC-DR", "moid": "datacenter-2", "config_status": "green", "overall_status": "green"},
                    ]
                },
                "clusters_info": {
                    # Ansible loop result shape: results list, one entry per datacenter
                    # Each entry has the cluster_info module output at top level
                    "results": [
                        {
                            "item": "DC-Production",
                            "clusters": {
                                "Prod-Cluster-01": {
                                    "datacenter": "DC-Production",
                                    "drs_enabled": True,
                                    "drs_default_vm_behavior": "fullyAutomated",
                                    "drs_vmotion_rate": 3,
                                    "dpm_enabled": False,
                                    "ha_enabled": True,
                                    "ha_admission_control_enabled": True,
                                    "ha_failover_level": 1,
                                    "ha_host_monitoring": "enabled",
                                    "ha_vm_monitoring": "vmMonitoringDisabled",
                                    "moid": "domain-c10",
                                    "vsan_enabled": False,
                                    "hosts": [
                                        {"name": "esxi01.corp.local", "folder": "/DC-Production/host/Prod-Cluster-01"},
                                        {"name": "esxi02.corp.local", "folder": "/DC-Production/host/Prod-Cluster-01"},
                                        {"name": "esxi03.corp.local", "folder": "/DC-Production/host/Prod-Cluster-01"},
                                    ],
                                    "resource_summary": {
                                        "cpuCapacityMHz": 192000,
                                        "cpuUsedMHz": 48000,
                                        "memCapacityMB": 786432,
                                        "memUsedMB": 524288,
                                        "storageCapacityMB": 76800000,
                                        "storageUsedMB": 25600000,
                                    },
                                    "tags": [],
                                },
                                "DR-Cluster-01": {
                                    "datacenter": "DC-Production",
                                    "drs_enabled": False,
                                    "drs_default_vm_behavior": "manual",
                                    "drs_vmotion_rate": 3,
                                    "dpm_enabled": False,
                                    "ha_enabled": False,
                                    "ha_admission_control_enabled": False,
                                    "ha_failover_level": 1,
                                    "ha_host_monitoring": "disabled",
                                    "ha_vm_monitoring": "vmMonitoringDisabled",
                                    "moid": "domain-c20",
                                    "vsan_enabled": False,
                                    "hosts": [
                                        {"name": "esxi04.corp.local", "folder": "/DC-Production/host/DR-Cluster-01"},
                                    ],
                                    "resource_summary": {
                                        "cpuCapacityMHz": 64000,
                                        "cpuUsedMHz": 4000,
                                        "memCapacityMB": 262144,
                                        "memUsedMB": 32768,
                                        "storageCapacityMB": 20480000,
                                        "storageUsedMB": 2048000,
                                    },
                                    "tags": [],
                                },
                            },
                        },
                    ],
                },
                "datastores_info": {"datastores": datastores},
                "vms_info": {"virtual_machines": vms},
                "snapshots_info": {"snapshots": snapshots},
                # internal.vmware.vmware_triggered_alarms_info returns {alarms, count, python}
                # — no payload wrapper
                "alarms_info": {
                    "alarms": alarms,
                    "count": len(alarms),
                    "python": "/usr/bin/python3",
                },
                "config": {"infrastructure_vm_patterns": ["^vCenter$", "^ESXi-.*$"]},
            },
        }
    }


# ---------------------------------------------------------------------------
# Multi-site vCenter factories
# ---------------------------------------------------------------------------

_VM_ROLES = [
    "web",
    "db",
    "app",
    "cache",
    "monitoring",
    "backup",
    "proxy",
    "auth",
    "api",
    "worker",
    "scheduler",
    "log",
]

_VM_SIZES: list[dict] = [
    {"allocated": {"cpu": 2, "memory": 4096, "storage": 107374182400}},
    {"allocated": {"cpu": 4, "memory": 8192, "storage": 214748364800}},
    {"allocated": {"cpu": 8, "memory": 16384, "storage": 429496729600}},
    {"allocated": {"cpu": 16, "memory": 32768, "storage": 858993459200}},
]


def _make_site_vms(
    count: int,
    datacenter: str,
    cluster_names: list[str],
    esxi_hosts: list[str],
    site_code: str,
    tools_issue_count: int = 0,
    powered_off_count: int = 0,
) -> list[dict]:
    """Generate `count` realistic VMs spread across clusters and ESXi hosts."""
    vms = []
    for i in range(count):
        role = _VM_ROLES[i % len(_VM_ROLES)]
        idx = i + 1
        name = f"{role}-{site_code}-{idx:03d}"
        cluster = cluster_names[i % len(cluster_names)]
        esxi = esxi_hosts[i % len(esxi_hosts)]
        moid = f"vm-{site_code}-{idx:04d}"
        uuid = f"4207{site_code[:4]}-{idx:04d}-3bd5-64dc-903fd3a0{idx:06d}"
        ip = f"10.{20 + list(_SITE_IP_OCTET.keys()).index(site_code) if site_code in _SITE_IP_OCTET else 30}.{(i // 254) + 1}.{(i % 254) + 1}"

        if i < powered_off_count:
            power_state, tools, ip_addr = "poweredOff", "toolsOk", ""
        elif i < powered_off_count + tools_issue_count // 2:
            power_state, tools, ip_addr = "poweredOn", "toolsNotRunning", ip
        elif i < powered_off_count + tools_issue_count:
            power_state, tools, ip_addr = "poweredOn", "toolsNotInstalled", ip
        else:
            power_state, tools, ip_addr = "poweredOn", "toolsOk", ip

        vm = _make_vm(
            name,
            power_state,
            tools,
            ip_addr,
            moid,
            uuid,
            datacenter=datacenter,
            cluster=cluster,
            esxi_hostname=esxi,
            guest_fullname="Ubuntu Linux (64-bit)"
            if role in ("web", "app", "api")
            else "Microsoft Windows Server 2022 (64-bit)",
            folder=f"/{datacenter}/vm/{role}",
            vm_network={},
            datastore_url=[{"name": f"ds-{cluster.lower()}-01", "url": f"/vmfs/volumes/{site_code}-{role}"}],
        )
        vm.update(_VM_SIZES[i % len(_VM_SIZES)])
        vms.append(vm)
    return vms


# Site-code → third IP octet
_SITE_IP_OCTET: dict[str, int] = {
    "use1": 10,
    "usw2": 11,
    "eude": 12,
    "euk": 13,
    "apsg": 14,
    "apau": 15,
}


def _make_site_cluster(
    name: str,
    datacenter: str,
    moid: str,
    esxi_hosts: list[str],
    folder: str,
    *,
    ha_enabled: bool = True,
    drs_enabled: bool = True,
    cpu_capacity_mhz: int = 256000,
    cpu_used_mhz: int = 64000,
    mem_capacity_mb: int = 524288,
    mem_used_mb: int = 196608,
) -> dict:
    """Build a realistic cluster dict matching vmware.vmware.cluster_info RETURN."""
    return {
        "datacenter": datacenter,
        "moid": moid,
        "ha_enabled": ha_enabled,
        "ha_admission_control_enabled": ha_enabled,
        "ha_failover_level": 1,
        "ha_host_monitoring": "enabled" if ha_enabled else "disabled",
        "ha_restart_priority": "medium",
        "ha_vm_failure_interval": 30,
        "ha_vm_max_failure_window": -1,
        "ha_vm_max_failures": 3,
        "ha_vm_min_up_time": 120,
        "ha_vm_monitoring": "vmMonitoringDisabled",
        "ha_vm_tools_monitoring": "vmMonitoringDisabled",
        "drs_enabled": drs_enabled,
        "drs_default_vm_behavior": "fullyAutomated" if drs_enabled else "manual",
        "drs_enable_vm_behavior_overrides": True,
        "drs_vmotion_rate": 3,
        "dpm_enabled": False,
        "dpm_default_dpm_behavior": "automated",
        "dpm_host_power_action_rate": 3,
        "vsan_enabled": False,
        "vsan_auto_claim_storage": False,
        "hosts": [{"name": h, "folder": f"{folder}/{name}"} for h in esxi_hosts],
        "resource_summary": {
            "cpuCapacityMHz": cpu_capacity_mhz,
            "cpuUsedMHz": cpu_used_mhz,
            "memCapacityMB": mem_capacity_mb,
            "memUsedMB": mem_used_mb,
            "pMemAvailableMB": 0,
            "pMemCapacityMB": 0,
            "storageCapacityMB": cpu_capacity_mhz * 80,
            "storageUsedMB": cpu_used_mhz * 80,
        },
        "tags": [],
    }


def make_vcenter_site_bundle(cfg: dict) -> dict:
    """Build a realistic multi-site vmware_raw_vcenter bundle from a site config dict.

    cfg keys:
      hostname      str  — vCenter FQDN used as bundle key
      site_code     str  — short code for IP/name generation (e.g. "use1")
      country       str  — country name for docstring clarity
      version       str  — VCSA version string
      build         str  — VCSA build number
      health        dict — {overall, cpu, memory, database, storage, swap}
      ssh           bool — SSH enabled on appliance
      shell         bool — interactive shell enabled
      backup_schedules list[dict] — schedule list ([] = no schedule)
      datacenters   list[dict] — [{name, moid, config_status, overall_status}]
      clusters      dict — {datacenter_name: {cluster_name: cluster_dict}}
      datastores    list[dict] — pre-built datastore dicts
      vm_count      int  — total VMs to generate
      vm_clusters   list[str] — cluster names VMs are distributed across
      vm_esxi       list[str] — ESXi FQDNs VMs are placed on
      vm_datacenter str  — datacenter name for all VMs
      tools_issues  int  — how many VMs have tools problems (split evenly not-running/not-installed)
      powered_off   int  — how many VMs are powered off
      snapshots     list[dict] — snapshot list
      alarms        list[dict] — alarm list
      ntp_mode      str  — NTP or host
    """
    hostname = cfg["hostname"]
    site_code = cfg["site_code"]

    health = cfg.get(
        "health",
        {
            "cpu": "green",
            "database": "green",
            "memory": "green",
            "overall": "green",
            "storage": "green",
            "swap": "green",
        },
    )
    ssh_enabled: bool = cfg.get("ssh", False)
    shell_str: str = "True" if cfg.get("shell", False) else "False"

    vms = _make_site_vms(
        count=cfg["vm_count"],
        datacenter=cfg["vm_datacenter"],
        cluster_names=cfg["vm_clusters"],
        esxi_hosts=cfg["vm_esxi"],
        site_code=site_code,
        tools_issue_count=cfg.get("tools_issues", 0),
        powered_off_count=cfg.get("powered_off", 0),
    )

    appliance = copy.deepcopy(_APPLIANCE_BASE)
    _a = appliance["appliance"]
    _a["summary"]["health"] = health
    _a["summary"]["uptime"] = str(cfg.get("uptime_seconds", 2592000.0))
    _a["summary"]["hostname"] = [hostname]
    _a["summary"]["build_number"] = cfg.get("build", "24022515")
    _a["summary"]["version"] = cfg.get("version", "8.0.3.00300")
    _a["summary"]["product"] = "VMware vCenter Server"
    _a["access"]["ssh"] = ssh_enabled
    _a["access"]["shell"]["enabled"] = shell_str
    _a["access"]["shell"]["timeout"] = "0"
    _a["time"]["time_sync"]["mode"] = cfg.get("ntp_mode", "NTP")
    _a["time"]["time_sync"]["servers"] = cfg.get("ntp_servers", ["time.google.com"])

    alarms = cfg.get("alarms", [])
    return {
        "vmware_raw_vcenter": {
            "metadata": {
                "host": hostname,
                "raw_type": "vcenter",
                "timestamp": _now_iso(),
                "engine": "ncs_collector_callback",
            },
            "data": {
                "appliance_health_info": appliance,
                "appliance_backup_info": {"schedules": cfg.get("backup_schedules", [])},
                "datacenters_info": {"datacenter_info": cfg.get("datacenters", [])},
                "clusters_info": {
                    "results": [
                        {
                            "item": dc_name,
                            "clusters": dc_clusters,
                            "failed": False,
                            "failed_when_result": False,
                        }
                        for dc_name, dc_clusters in cfg.get("clusters", {}).items()
                    ]
                },
                "datastores_info": {"datastores": cfg.get("datastores", [])},
                "vms_info": {"virtual_machines": vms},
                "snapshots_info": {"snapshots": cfg.get("snapshots", [])},
                "alarms_info": {
                    "alarms": alarms,
                    "count": len(alarms),
                    "python": "/usr/bin/python3",
                },
                "config": cfg.get("config", {"infrastructure_vm_patterns": ["^vCenter$", "^ESXi-.*$"]}),
            },
        }
    }


# ---------------------------------------------------------------------------
# Site definitions — 6 sites, ~300 VMs total
# ---------------------------------------------------------------------------


def _backup_sched(enabled: bool = True) -> dict:
    return {
        "name": "daily-backup",
        "enabled": enabled,
        "fast_backup": False,
        "location": "nfs://10.0.0.100:/nfs/vcenter-backup/",
        "location_user": "vcbackup",
        "includes_stats_events_and_tasks": True,
        "includes_supervisors_control_plane": False,
        "retain_count": 5,
        "schedule": {"days_of_week": ["SUNDAY"], "hour": 1, "minute": 30},
    }


# --- USA East (Virginia) — 75 VMs, 3 clusters, degraded storage + alarm ---
SITE_US_EAST: dict = {
    "hostname": "vcenter-us-east.corp.local",
    "site_code": "use1",
    "country": "USA (Virginia)",
    "version": "8.0.3.00300",
    "build": "24022515",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "green",
        "overall": "green",
        "storage": "green",
        "swap": "green",
    },
    "ssh": False,
    "shell": False,
    "backup_schedules": [_backup_sched(enabled=True)],
    "datacenters": [
        {"name": "DC-US-East-1", "moid": "datacenter-10", "config_status": "green", "overall_status": "green"},
    ],
    "clusters": {
        "DC-US-East-1": {
            "Prod-Cluster-A": _make_site_cluster(
                "Prod-Cluster-A",
                "DC-US-East-1",
                "domain-c101",
                [
                    "esxi01.use1.corp.local",
                    "esxi02.use1.corp.local",
                    "esxi03.use1.corp.local",
                    "esxi04.use1.corp.local",
                ],
                "/DC-US-East-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=512000,
                cpu_used_mhz=220000,
                mem_capacity_mb=1572864,
                mem_used_mb=900000,
            ),
            "Prod-Cluster-B": _make_site_cluster(
                "Prod-Cluster-B",
                "DC-US-East-1",
                "domain-c102",
                [
                    "esxi05.use1.corp.local",
                    "esxi06.use1.corp.local",
                    "esxi07.use1.corp.local",
                    "esxi08.use1.corp.local",
                ],
                "/DC-US-East-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=512000,
                cpu_used_mhz=280000,
                mem_capacity_mb=1572864,
                mem_used_mb=1100000,
            ),
            "DR-Cluster": _make_site_cluster(
                "DR-Cluster",
                "DC-US-East-1",
                "domain-c103",
                ["esxi09.use1.corp.local", "esxi10.use1.corp.local"],
                "/DC-US-East-1/host",
                ha_enabled=False,
                drs_enabled=False,
                cpu_capacity_mhz=128000,
                cpu_used_mhz=20000,
                mem_capacity_mb=393216,
                mem_used_mb=49152,
            ),
        }
    },
    "datastores": [
        _make_ds("USE1-VMFS-SSD-01", 21990232555520, 10995116277760, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("USE1-VMFS-SSD-02", 21990232555520, 10995116277760, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "USE1-VMFS-SSD-03", 21990232555520, 2199023255552, maintenanceMode="normal", multipleHostAccess=True
        ),  # 10% → critical
        _make_ds(
            "USE1-VMFS-SSD-04", 21990232555520, 3298534883328, maintenanceMode="normal", multipleHostAccess=True
        ),  # 15% → warning
        _make_ds(
            "USE1-NFS-01",
            43980465111040,
            21990232555520,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "USE1-NFS-02",
            43980465111040,
            30786325577728,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds("USE1-DR-VMFS-01", 10995116277760, 8796093022208, maintenanceMode="normal", multipleHostAccess=False),
        _make_ds(
            "USE1-NFS-BACKUP",
            87960930222080,
            70368744177664,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
    ],
    "vm_count": 75,
    "vm_datacenter": "DC-US-East-1",
    "vm_clusters": ["Prod-Cluster-A", "Prod-Cluster-B", "DR-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.use1.corp.local" for i in range(1, 11)],
    "tools_issues": 4,
    "powered_off": 5,
    "snapshots": [
        {
            "vm_name": "db-use1-004",
            "folder": "/DC-US-East-1/vm/db",
            "name": "pre-migration",
            "description": "Pre-DB migration snapshot",
            "creation_time": _days_ago_iso(12),
            "state": "poweredOn",
            "id": 1,
            "quiesced": True,
        },
        {
            "vm_name": "app-use1-009",
            "folder": "/DC-US-East-1/vm/app",
            "name": "pre-patch-q1",
            "description": "Q1 patching baseline",
            "creation_time": _days_ago_iso(35),
            "state": "poweredOn",
            "id": 2,
            "quiesced": False,
        },
        {
            "vm_name": "web-use1-001",
            "folder": "/DC-US-East-1/vm/web",
            "name": "rollback",
            "description": "Emergency rollback point",
            "creation_time": _days_ago_iso(3),
            "state": "poweredOn",
            "id": 3,
            "quiesced": False,
        },
    ],
    "alarms": [
        {
            "alarm_name": "Datastore Free Space",
            "description": "USE1-VMFS-SSD-03 <10% free",
            "entity": "USE1-VMFS-SSD-03",
            "entity_type": "Datastore",
            "status": "red",
            "severity": "critical",
            "time": _days_ago_iso(0.5),
            "acknowledged": False,
        },
        {
            "alarm_name": "Host Memory Usage",
            "description": "esxi06.use1 memory >95%",
            "entity": "esxi06.use1.corp.local",
            "entity_type": "HostSystem",
            "status": "yellow",
            "severity": "warning",
            "time": _days_ago_iso(2),
            "acknowledged": False,
        },
    ],
}

# --- USA West (Oregon) — 40 VMs, 2 clusters, fully healthy ---
SITE_US_WEST: dict = {
    "hostname": "vcenter-us-west.corp.local",
    "site_code": "usw2",
    "country": "USA (Oregon)",
    "version": "8.0.2.00200",
    "build": "22617221",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "green",
        "overall": "green",
        "storage": "green",
        "swap": "green",
    },
    "ssh": False,
    "shell": False,
    "backup_schedules": [_backup_sched(enabled=True)],
    "datacenters": [
        {"name": "DC-US-West-1", "moid": "datacenter-20", "config_status": "green", "overall_status": "green"},
    ],
    "clusters": {
        "DC-US-West-1": {
            "Prod-Cluster-Main": _make_site_cluster(
                "Prod-Cluster-Main",
                "DC-US-West-1",
                "domain-c201",
                ["esxi01.usw2.corp.local", "esxi02.usw2.corp.local", "esxi03.usw2.corp.local"],
                "/DC-US-West-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=384000,
                cpu_used_mhz=120000,
                mem_capacity_mb=786432,
                mem_used_mb=262144,
            ),
            "Edge-Cluster": _make_site_cluster(
                "Edge-Cluster",
                "DC-US-West-1",
                "domain-c202",
                ["esxi04.usw2.corp.local", "esxi05.usw2.corp.local"],
                "/DC-US-West-1/host",
                ha_enabled=True,
                drs_enabled=False,
                cpu_capacity_mhz=128000,
                cpu_used_mhz=32000,
                mem_capacity_mb=262144,
                mem_used_mb=65536,
            ),
        }
    },
    "datastores": [
        _make_ds("USW2-VMFS-SSD-01", 21990232555520, 13194139533312, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("USW2-VMFS-SSD-02", 21990232555520, 15393162788864, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "USW2-NFS-01",
            43980465111040,
            35184372088832,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "USW2-NFS-BACKUP",
            43980465111040,
            39582418599936,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
    ],
    "vm_count": 40,
    "vm_datacenter": "DC-US-West-1",
    "vm_clusters": ["Prod-Cluster-Main", "Edge-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.usw2.corp.local" for i in range(1, 6)],
    "tools_issues": 0,
    "powered_off": 2,
    "snapshots": [],
    "alarms": [],
}

# --- Europe / Germany (Frankfurt) — 65 VMs, 2 clusters, appliance health yellow + aged snaps ---
SITE_EU_DE: dict = {
    "hostname": "vcenter-eu-de.corp.local",
    "site_code": "eude",
    "country": "Germany (Frankfurt)",
    "version": "8.0.3.00300",
    "build": "24022515",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "yellow",
        "overall": "yellow",
        "storage": "green",
        "swap": "green",
    },
    "ssh": False,
    "shell": False,
    "backup_schedules": [_backup_sched(enabled=True)],
    "datacenters": [
        {"name": "DC-EU-Central-1", "moid": "datacenter-30", "config_status": "green", "overall_status": "yellow"},
    ],
    "clusters": {
        "DC-EU-Central-1": {
            "EU-Prod-Cluster-01": _make_site_cluster(
                "EU-Prod-Cluster-01",
                "DC-EU-Central-1",
                "domain-c301",
                [f"esxi{i:02d}.eude.corp.local" for i in range(1, 7)],
                "/DC-EU-Central-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=768000,
                cpu_used_mhz=490000,
                mem_capacity_mb=2097152,
                mem_used_mb=1835008,  # ~87% — causes yellow health
            ),
            "EU-Dev-Cluster": _make_site_cluster(
                "EU-Dev-Cluster",
                "DC-EU-Central-1",
                "domain-c302",
                ["esxi07.eude.corp.local", "esxi08.eude.corp.local"],
                "/DC-EU-Central-1/host",
                ha_enabled=False,
                drs_enabled=False,
                cpu_capacity_mhz=128000,
                cpu_used_mhz=40000,
                mem_capacity_mb=262144,
                mem_used_mb=73728,
            ),
        }
    },
    "datastores": [
        _make_ds("EUDE-VMFS-SSD-01", 32985348833280, 16492674416640, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("EUDE-VMFS-SSD-02", 32985348833280, 18691697671168, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "EUDE-VMFS-SSD-03", 32985348833280, 14293651161088, maintenanceMode="normal", multipleHostAccess=True
        ),  # 43% — OK
        _make_ds(
            "EUDE-NFS-01",
            65970697666560,
            42949672960000,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "EUDE-NFS-02",
            65970697666560,
            52428800000000,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "EUDE-NFS-BACKUP",
            131941395333120,
            105553116266496,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
    ],
    "vm_count": 65,
    "vm_datacenter": "DC-EU-Central-1",
    "vm_clusters": ["EU-Prod-Cluster-01", "EU-Dev-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.eude.corp.local" for i in range(1, 9)],
    "tools_issues": 0,
    "powered_off": 8,
    "snapshots": [
        {
            "vm_name": "db-eude-002",
            "folder": "/DC-EU-Central-1/vm/db",
            "name": "pre-gdpr-audit",
            "description": "GDPR compliance audit baseline",
            "creation_time": _days_ago_iso(55),
            "state": "poweredOff",
            "id": 10,
            "quiesced": False,
        },
        {
            "vm_name": "app-eude-006",
            "folder": "/DC-EU-Central-1/vm/app",
            "name": "q4-baseline",
            "description": "Q4 application baseline",
            "creation_time": _days_ago_iso(90),
            "state": "poweredOn",
            "id": 11,
            "quiesced": False,
        },
        {
            "vm_name": "api-eude-003",
            "folder": "/DC-EU-Central-1/vm/api",
            "name": "api-v2-rollback",
            "description": "API v2 deployment rollback",
            "creation_time": _days_ago_iso(14),
            "state": "poweredOn",
            "id": 12,
            "quiesced": True,
        },
        {
            "vm_name": "web-eude-001",
            "folder": "/DC-EU-Central-1/vm/web",
            "name": "web-pre-upgrade",
            "description": "Before web stack upgrade",
            "creation_time": _days_ago_iso(21),
            "state": "poweredOn",
            "id": 13,
            "quiesced": False,
        },
    ],
    "alarms": [
        {
            "alarm_name": "vCenter Memory Usage",
            "description": "VCSA appliance memory >80%",
            "entity": "vcenter-eu-de.corp.local",
            "entity_type": "VirtualMachine",
            "status": "yellow",
            "severity": "warning",
            "time": _days_ago_iso(1),
            "acknowledged": False,
        },
        {
            "alarm_name": "Cluster Memory Usage",
            "description": "EU-Prod-Cluster-01 memory utilisation >85%",
            "entity": "EU-Prod-Cluster-01",
            "entity_type": "ClusterComputeResource",
            "status": "yellow",
            "severity": "warning",
            "time": _days_ago_iso(0.5),
            "acknowledged": False,
        },
    ],
}

# --- Europe / UK (London) — 30 VMs, 1 cluster, backup disabled + SSH/shell open ---
SITE_EU_UK: dict = {
    "hostname": "vcenter-eu-uk.corp.local",
    "site_code": "euk",
    "country": "United Kingdom (London)",
    "version": "7.0.3.01800",
    "build": "21784236",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "green",
        "overall": "green",
        "storage": "green",
        "swap": "green",
    },
    "ssh": True,  # ssh_enabled WARNING
    "shell": True,  # shell_enabled WARNING
    "backup_schedules": [_backup_sched(enabled=False)],  # backup_schedule_disabled CRITICAL
    "datacenters": [
        {"name": "DC-EU-West-1", "moid": "datacenter-40", "config_status": "green", "overall_status": "green"},
    ],
    "clusters": {
        "DC-EU-West-1": {
            "UK-Prod-Cluster": _make_site_cluster(
                "UK-Prod-Cluster",
                "DC-EU-West-1",
                "domain-c401",
                [f"esxi{i:02d}.euk.corp.local" for i in range(1, 5)],
                "/DC-EU-West-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=256000,
                cpu_used_mhz=89600,
                mem_capacity_mb=524288,
                mem_used_mb=183500,
            ),
        }
    },
    "datastores": [
        _make_ds("EUK-VMFS-SSD-01", 10995116277760, 7696581394432, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("EUK-VMFS-SSD-02", 10995116277760, 5497558138880, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "EUK-NFS-01",
            21990232555520,
            3298534883328,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),  # 15% → warning
        _make_ds(
            "EUK-NFS-BACKUP",
            21990232555520,
            17592186044416,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
    ],
    "vm_count": 30,
    "vm_datacenter": "DC-EU-West-1",
    "vm_clusters": ["UK-Prod-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.euk.corp.local" for i in range(1, 5)],
    "tools_issues": 0,
    "powered_off": 2,
    "snapshots": [],
    "alarms": [],
}

# --- APAC / Singapore — 55 VMs, 2 clusters, tools issues + critical alarm ---
SITE_APAC_SG: dict = {
    "hostname": "vcenter-apac-sg.corp.local",
    "site_code": "apsg",
    "country": "Singapore",
    "version": "8.0.3.00300",
    "build": "24022515",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "green",
        "overall": "green",
        "storage": "green",
        "swap": "green",
    },
    "ssh": False,
    "shell": False,
    "backup_schedules": [_backup_sched(enabled=True)],
    "datacenters": [
        {"name": "DC-APAC-SG-1", "moid": "datacenter-50", "config_status": "green", "overall_status": "green"},
    ],
    "clusters": {
        "DC-APAC-SG-1": {
            "APAC-Prod-Cluster": _make_site_cluster(
                "APAC-Prod-Cluster",
                "DC-APAC-SG-1",
                "domain-c501",
                [f"esxi{i:02d}.apsg.corp.local" for i in range(1, 7)],
                "/DC-APAC-SG-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=768000,
                cpu_used_mhz=360000,
                mem_capacity_mb=1572864,
                mem_used_mb=786432,
            ),
            "APAC-Edge-Cluster": _make_site_cluster(
                "APAC-Edge-Cluster",
                "DC-APAC-SG-1",
                "domain-c502",
                ["esxi07.apsg.corp.local", "esxi08.apsg.corp.local"],
                "/DC-APAC-SG-1/host",
                ha_enabled=True,
                drs_enabled=False,
                cpu_capacity_mhz=192000,
                cpu_used_mhz=48000,
                mem_capacity_mb=393216,
                mem_used_mb=98304,
            ),
        }
    },
    "datastores": [
        _make_ds("APSG-VMFS-SSD-01", 21990232555520, 10995116277760, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("APSG-VMFS-SSD-02", 21990232555520, 10995116277760, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "APSG-VMFS-SSD-03", 21990232555520, 2857749006336, maintenanceMode="normal", multipleHostAccess=True
        ),  # 13% → warning
        _make_ds(
            "APSG-NFS-01",
            43980465111040,
            26388279066624,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "APSG-NFS-BACKUP",
            65970697666560,
            52776558133248,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
        _make_ds(
            "APSG-CRASH-NFS",
            5497558138880,
            0,
            ds_type="NFS",
            accessible=False,
            maintenanceMode="normal",
            multipleHostAccess=False,
        ),  # inaccessible → CRITICAL
    ],
    "vm_count": 55,
    "vm_datacenter": "DC-APAC-SG-1",
    "vm_clusters": ["APAC-Prod-Cluster", "APAC-Edge-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.apsg.corp.local" for i in range(1, 9)],
    "tools_issues": 8,  # vm_tools_not_running + vm_tools_not_installed
    "powered_off": 3,
    "snapshots": [
        {
            "vm_name": "db-apsg-004",
            "folder": "/DC-APAC-SG-1/vm/db",
            "name": "pre-release-2.4",
            "description": "Pre-release 2.4 snapshot",
            "creation_time": _days_ago_iso(9),
            "state": "poweredOn",
            "id": 20,
            "quiesced": True,
        },
    ],
    "alarms": [
        {
            "alarm_name": "Datastore Inaccessible",
            "description": "APSG-CRASH-NFS is inaccessible",
            "entity": "APSG-CRASH-NFS",
            "entity_type": "Datastore",
            "status": "red",
            "severity": "critical",
            "time": _days_ago_iso(0.1),
            "acknowledged": False,
        },
        {
            "alarm_name": "Host Network Connectivity",
            "description": "esxi08.apsg NIC teaming failure",
            "entity": "esxi08.apsg.corp.local",
            "entity_type": "HostSystem",
            "status": "yellow",
            "severity": "warning",
            "time": _days_ago_iso(0.3),
            "acknowledged": False,
        },
    ],
}

# --- APAC / Australia (Sydney) — 35 VMs, 1 cluster, no backup schedule ---
SITE_APAC_AU: dict = {
    "hostname": "vcenter-apac-au.corp.local",
    "site_code": "apau",
    "country": "Australia (Sydney)",
    "version": "8.0.2.00200",
    "build": "22617221",
    "health": {
        "cpu": "green",
        "database": "green",
        "memory": "green",
        "overall": "green",
        "storage": "green",
        "swap": "green",
    },
    "ssh": False,
    "shell": False,
    "backup_schedules": [],  # no_backup_schedule CRITICAL
    "datacenters": [
        {"name": "DC-APAC-AU-1", "moid": "datacenter-60", "config_status": "green", "overall_status": "green"},
    ],
    "clusters": {
        "DC-APAC-AU-1": {
            "AU-Prod-Cluster": _make_site_cluster(
                "AU-Prod-Cluster",
                "DC-APAC-AU-1",
                "domain-c601",
                [f"esxi{i:02d}.apau.corp.local" for i in range(1, 5)],
                "/DC-APAC-AU-1/host",
                ha_enabled=True,
                drs_enabled=True,
                cpu_capacity_mhz=256000,
                cpu_used_mhz=51200,
                mem_capacity_mb=524288,
                mem_used_mb=104857,
            ),
        }
    },
    "datastores": [
        _make_ds("APAU-VMFS-SSD-01", 10995116277760, 8796093022208, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds("APAU-VMFS-SSD-02", 10995116277760, 7696581394432, maintenanceMode="normal", multipleHostAccess=True),
        _make_ds(
            "APAU-NFS-01",
            21990232555520,
            17592186044416,
            ds_type="NFS",
            maintenanceMode="normal",
            multipleHostAccess=True,
        ),
    ],
    "vm_count": 35,
    "vm_datacenter": "DC-APAC-AU-1",
    "vm_clusters": ["AU-Prod-Cluster"],
    "vm_esxi": [f"esxi{i:02d}.apau.corp.local" for i in range(1, 5)],
    "tools_issues": 0,
    "powered_off": 3,
    "snapshots": [],
    "alarms": [],
}

ALL_VCENTER_SITES = [SITE_US_EAST, SITE_US_WEST, SITE_EU_DE, SITE_EU_UK, SITE_APAC_SG, SITE_APAC_AU]


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def make_windows_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    """Build a realistic windows_raw_audit bundle.

    ccm_service is built from ansible.windows.win_service RETURN sample keys,
    then overridden for the scenario.  win_service returns lowercase state
    ("running", "stopped", etc.).  The ccmexec_not_running alert uses ne_str
    against "running".

    configmgr_apps and installed_apps are stored as pre-parsed values matching
    what production audit.yaml stores after ``_configmgr_apps_result.output[0] | from_json``
    and ``_installed_apps_result.output[0] | from_json``.

    unhealthy=True triggers: ccmexec_not_running, failed_updates, apps_pending_update.
    unhealthy=False → healthy host, no alerts.
    """
    if unhealthy:
        ccm_state = "stopped"
        audit_failed = False
        update_results: list[dict] = [
            {"application": "Microsoft Visual C++ 2019 Redistributable (x64)", "status": "failed", "failed": True},
            {"application": "Windows Defender ATP", "status": "succeeded", "failed": False},
        ]
        # Pre-parsed dict — matches what applications.yaml stores via from_json
        configmgr_apps: dict = {
            "AllApps": [
                {
                    "Name": "Microsoft Office 365 ProPlus",
                    "Version": "16.0.17628.20006",
                    "Publisher": "Microsoft Corporation",
                },
                {"Name": "Microsoft Visual Studio Code", "Version": "1.86.2", "Publisher": "Microsoft Corporation"},
                {"Name": "Google Chrome", "Version": "121.0.6167.185", "Publisher": "Google LLC"},
                {"Name": "Mozilla Firefox ESR", "Version": "115.7.0", "Publisher": "Mozilla"},
                {"Name": "7-Zip 23.01 (x64)", "Version": "23.01.00.0", "Publisher": "Igor Pavlov"},
                {"Name": "Python 3.11.7", "Version": "3.11.7150.0", "Publisher": "Python Software Foundation"},
                {"Name": "Notepad++", "Version": "8.6.2", "Publisher": "Notepad++ Team"},
                {"Name": "WinRAR 6.24 (64-bit)", "Version": "6.24.0", "Publisher": "win.rar GmbH"},
                {"Name": "Adobe Acrobat Reader DC", "Version": "23.008.20533", "Publisher": "Adobe"},
                {"Name": "Microsoft Teams", "Version": "1.6.00.33362", "Publisher": "Microsoft Corporation"},
            ],
            "AppsToUpdate": [
                {"Name": "Google Chrome", "CurrentVersion": "121.0.6167.185", "TargetVersion": "122.0.6261.57"},
                {"Name": "Adobe Acrobat Reader DC", "CurrentVersion": "23.008.20533", "TargetVersion": "24.001.20604"},
            ],
        }
    else:
        ccm_state = "running"
        audit_failed = False
        update_results = [
            {"application": "Windows Defender ATP", "status": "succeeded", "failed": False},
        ]
        configmgr_apps = {
            "AllApps": [
                {
                    "Name": "Microsoft Office 365 ProPlus",
                    "Version": "16.0.17628.20006",
                    "Publisher": "Microsoft Corporation",
                },
                {"Name": "Google Chrome", "Version": "122.0.6261.57", "Publisher": "Google LLC"},
            ],
            "AppsToUpdate": [],
        }

    # Pre-parsed list — matches what applications.yaml stores via from_json
    installed_apps: list[dict] = [
        {"Name": "Microsoft Office 365 ProPlus", "Version": "16.0.17628.20006", "Publisher": "Microsoft Corporation"},
        {"Name": "Google Chrome", "Version": "121.0.6167.185", "Publisher": "Google LLC"},
        {"Name": "7-Zip 23.01 (x64)", "Version": "23.01.00.0", "Publisher": "Igor Pavlov"},
        {
            "Name": "Microsoft Visual C++ 2015-2022 Redistributable (x64)",
            "Version": "14.38.33130.0",
            "Publisher": "Microsoft Corporation",
        },
        {
            "Name": "Microsoft Visual C++ 2015-2022 Redistributable (x86)",
            "Version": "14.38.33130.0",
            "Publisher": "Microsoft Corporation",
        },
        {"Name": "Mozilla Firefox ESR 115.7.0 (x64 en-US)", "Version": "115.7.0", "Publisher": "Mozilla"},
        {"Name": "Python 3.11.7 (64-bit)", "Version": "3.11.7150.0", "Publisher": "Python Software Foundation"},
        {"Name": "Windows Admin Center", "Version": "2306.2306.16001.0", "Publisher": "Microsoft Corporation"},
        {"Name": "Notepad++ (64-bit x64)", "Version": "8.6.2", "Publisher": "Notepad++ Team"},
        {"Name": "Git version 2.43.0", "Version": "2.43.0", "Publisher": "The Git Development Community"},
        {"Name": "Microsoft Teams classic", "Version": "1.6.00.33362", "Publisher": "Microsoft Corporation"},
        {"Name": "Adobe Acrobat Reader DC (64-bit)", "Version": "23.008.20533", "Publisher": "Adobe"},
        {"Name": "PowerShell 7.4.1.500", "Version": "7.4.1.500", "Publisher": "Microsoft Corporation"},
        {"Name": "WinRAR 6.24 (64-bit)", "Version": "6.24.0", "Publisher": "win.rar GmbH"},
        {"Name": "Sysinternals Suite", "Version": "2024.01.01", "Publisher": "Microsoft Corporation"},
    ]

    # Build ccm_service from win_service RETURN sample keys, then override for scenario.
    # win_service RETURN has flat top-level keys: exists, name, state, start_mode, etc.
    ccm_service = copy.deepcopy(_WIN_SVC_BASE)
    ccm_service.update(
        {
            "exists": True,
            "name": "CcmExec",
            "display_name": "SMS Agent Host",
            "state": ccm_state,  # "running" or "stopped" (lowercase, as module returns)
            "start_mode": "auto",
            "path": "C:\\Windows\\CCM\\CcmExec.exe",
            "description": "Configuration Manager client agent",
            "username": "LocalSystem",
            "desktop_interact": False,
            "dependencies": ["RpcSs"],  # module sample has False; override to real list
            "depended_by": [],
        }
    )

    return {
        "windows_raw_audit": {
            "metadata": {
                "host": hostname,
                "raw_type": "audit",
                "timestamp": _now_iso(),
                "engine": "ncs_collector_callback",
            },
            "data": {
                "ansible_facts": {},
                "ccm_service": ccm_service,
                "configmgr_apps": configmgr_apps,
                "installed_apps": installed_apps,
                "apps_to_update": configmgr_apps["AppsToUpdate"],
                "update_results": update_results,
                "audit_failed": audit_failed,
            },
        }
    }


# ---------------------------------------------------------------------------
# STIG Reports
# ---------------------------------------------------------------------------


def make_stig_esxi_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    findings = [
        {
            "id": "V-256379",
            "status": "failed" if unhealthy else "pass",
            "severity": "high",
            "title": "ESXi must separate management networks.",
        },
        {"id": "V-256380", "status": "pass", "severity": "high", "title": "ESXi must restrict access."},
        {
            "id": "V-256381",
            "status": "failed" if unhealthy else "pass",
            "severity": "medium",
            "title": "ESXi must use NTP.",
        },
        {"id": "V-256382", "status": "pass", "severity": "medium", "title": "ESXi must use syslog."},
        {
            "id": "V-256383",
            "status": "failed" if unhealthy else "pass",
            "severity": "low",
            "title": "ESXi must have lockdown mode.",
        },
        {"id": "V-256384", "status": "pass", "severity": "low", "title": "ESXi must configure SSH timeout."},
        {"id": "V-256385", "status": "na", "severity": "low", "title": "ESXi some N/A check."},
        {"id": "V-256386", "status": "pass", "severity": "medium", "title": "ESXi another pass check."},
        {"id": "V-256387", "status": "pass", "severity": "high", "title": "ESXi yet another pass."},
        {"id": "V-256388", "status": "na", "severity": "high", "title": "ESXi another N/A check."},
    ]
    return {
        "vmware_raw_stig_esxi": {
            "metadata": {
                "host": hostname,
                "raw_type": "stig_esxi",
                "audit_type": "stig_esxi",
                "timestamp": _now_iso(),
            },
            "target_type": "esxi",
            "data": findings,
        }
    }


def make_stig_vm_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    findings = [
        {
            "id": "V-256400",
            "status": "failed" if unhealthy else "pass",
            "severity": "high",
            "title": "VM must disable unneeded hardware.",
        },
        {"id": "V-256401", "status": "pass", "severity": "high", "title": "VM must use encryption."},
        {
            "id": "V-256402",
            "status": "failed" if unhealthy else "pass",
            "severity": "medium",
            "title": "VM must restrict console access.",
        },
        {"id": "V-256403", "status": "pass", "severity": "medium", "title": "VM must use latest tools."},
        {"id": "V-256404", "status": "pass", "severity": "low", "title": "VM must limit logging."},
    ]
    return {
        "vmware_raw_stig_vm": {
            "metadata": {
                "host": hostname,
                "raw_type": "stig_vm",
                "audit_type": "stig_vm",
                "timestamp": _now_iso(),
            },
            "target_type": "vm",
            "data": findings,
        }
    }


def make_stig_ubuntu_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    findings = [
        {
            "id": "UBTU-22-010000",
            "status": "failed" if unhealthy else "pass",
            "severity": "high",
            "title": "Ubuntu must disable root login.",
        },
        {
            "id": "UBTU-22-010001",
            "status": "pass",
            "severity": "high",
            "title": "Ubuntu must require strong passwords.",
        },
        {
            "id": "UBTU-22-010002",
            "status": "failed" if unhealthy else "pass",
            "severity": "medium",
            "title": "Ubuntu must configure auditd.",
        },
        {"id": "UBTU-22-010003", "status": "pass", "severity": "medium", "title": "Ubuntu must use FIPS mode."},
        {"id": "UBTU-22-010004", "status": "pass", "severity": "low", "title": "Ubuntu must clear tmp."},
        {
            "id": "UBTU-22-010005",
            "status": "pass",
            "severity": "low",
            "title": "Ubuntu must disable unneeded services.",
        },
        {"id": "UBTU-22-010006", "status": "na", "severity": "medium", "title": "Ubuntu NA check."},
        {"id": "UBTU-22-010007", "status": "pass", "severity": "high", "title": "Ubuntu final check."},
    ]
    return {
        "ubuntu_raw_stig_ubuntu": {
            "metadata": {
                "host": hostname,
                "raw_type": "stig_ubuntu",
                "audit_type": "stig_ubuntu",
                "timestamp": _now_iso(),
            },
            "target_type": "ubuntu",
            "data": findings,
        }
    }


def make_stig_windows_bundle(hostname: str, *, unhealthy: bool = True) -> dict:
    findings = [
        {
            "id": "WN22-00-000000",
            "status": "failed" if unhealthy else "pass",
            "severity": "high",
            "title": "Windows must disable Guest account.",
        },
        {
            "id": "WN22-00-000001",
            "status": "pass",
            "severity": "high",
            "title": "Windows must enforce password history.",
        },
        {
            "id": "WN22-00-000002",
            "status": "failed" if unhealthy else "pass",
            "severity": "medium",
            "title": "Windows must enable Firewall.",
        },
        {"id": "WN22-00-000003", "status": "pass", "severity": "medium", "title": "Windows must disable SMBv1."},
        {"id": "WN22-00-000004", "status": "pass", "severity": "low", "title": "Windows must set legal notice."},
        {"id": "WN22-00-000005", "status": "pass", "severity": "low", "title": "Windows must disable autorun."},
        {"id": "WN22-00-000006", "status": "na", "severity": "medium", "title": "Windows NA check."},
        {"id": "WN22-00-000007", "status": "pass", "severity": "high", "title": "Windows final check."},
    ]
    return {
        "windows_raw_stig_windows": {
            "metadata": {
                "host": hostname,
                "raw_type": "stig_windows",
                "audit_type": "stig_windows",
                "timestamp": _now_iso(),
            },
            "target_type": "windows",
            "data": findings,
        }
    }
