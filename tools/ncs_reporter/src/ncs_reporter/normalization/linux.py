"""Linux-specific normalization logic for raw discovery/audit data."""

import logging
import re
from typing import Any

from ncs_reporter.models.base import MetadataModel, SummaryModel, AlertModel
from ncs_reporter.models.linux import LinuxAuditModel, LinuxContext
from ncs_reporter.alerts import (
    append_alerts,
    build_alerts,
    compute_audit_rollups,
)
from ncs_reporter.primitives import build_threshold_alert, safe_list, to_float, to_int

logger = logging.getLogger(__name__)


def build_storage_inventory(mounts: list[Any]) -> list[dict[str, Any]]:
    results = []
    for mount in safe_list(mounts):
        if not isinstance(mount, dict):
            continue
        device = str(mount.get("device") or "")
        if "loop" in device or "tmpfs" in device:
            continue

        size_total = to_float(mount.get("size_total"), 0.0)
        size_available = to_float(mount.get("size_available"), 0.0)
        used_pct = (
            ((size_total - size_available) / size_total * 100.0)
            if size_total > 0
            else 0.0
        )

        results.append(
            {
                "mount": mount.get("mount"),
                "device": device,
                "fstype": mount.get("fstype"),
                "total_gb": round(size_total / 1073741824.0, 1),
                "free_gb": round(size_available / 1073741824.0, 1),
                "used_pct": round(used_pct, 1),
            }
        )
    return results


def build_user_inventory(getent_passwd: dict[str, Any], shadow_lines: list[Any], epoch_seconds: int) -> list[dict[str, Any]]:
    getent_passwd = dict(getent_passwd or {})
    shadow_lines = safe_list(shadow_lines)
    epoch_days = to_int(epoch_seconds, 0) // 86400

    shadow_map = {}
    for line in shadow_lines:
        line = str(line or "").strip()
        if not line or ":" not in line or line.startswith("#"):
            continue
        user = line.split(":", 1)[0]
        if user:
            shadow_map[user] = line

    results = []
    for user, info in getent_passwd.items():
        info = safe_list(info)
        shadow = shadow_map.get(str(user), "")
        parts = shadow.split(":")
        last_change = to_int(parts[2], 0) if len(parts) > 2 else 0
        results.append(
            {
                "name": str(user),
                "uid": info[1] if len(info) > 1 else "",
                "gid": info[2] if len(info) > 2 else "",
                "home": info[4] if len(info) > 4 else "",
                "shell": info[5] if len(info) > 5 else "",
                "password_age_days": (epoch_days - last_change)
                if last_change > 0
                else -1,
            }
        )
    return results


def parse_sshd_config(stdout_lines: list[Any]) -> dict[str, str]:
    out = {}
    for line in safe_list(stdout_lines):
        line = str(line or "").strip()
        if not line or line.startswith("#"):
            continue
        
        parts = re.split(r"\s+", line, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            val = parts[1].split("#", 1)[0].strip()
            out[parts[0]] = val
    return out


def parse_apt_simulate_output(stdout_lines: list[Any]) -> int:
    for line in reversed(safe_list(stdout_lines)):
        line = str(line or "")
        match = re.search(r"(\d+)\s+upgraded,", line)
        if match:
            return to_int(match.group(1), 0)
    return 0


def normalize_linux(raw_bundle: dict[str, Any], config: dict[str, Any] | None = None) -> LinuxAuditModel:
    """
    Main entry point for normalizing raw Linux data.
    """
    config = dict(config or {})
    logger.debug("normalize_linux: raw_bundle keys=%s", list(raw_bundle.keys()))
    discovery_raw = raw_bundle.get("raw_discovery") or raw_bundle.get("discovery") or raw_bundle
    
    if isinstance(discovery_raw, dict) and "data" in discovery_raw:
        metadata_raw = discovery_raw.get("metadata", {})
        collected_at = metadata_raw.get("timestamp", "")
        payload = discovery_raw.get("data", {})
    else:
        collected_at = ""
        payload = discovery_raw

    ansible_facts = payload.get("ansible_facts", {})
    mounts = ansible_facts.get("mounts", [])
    getent_passwd = ansible_facts.get("getent_passwd", {})
    shadow_raw = payload.get("shadow_raw", {})
    sshd_raw = payload.get("sshd_raw", {})
    failed_services_raw = payload.get("failed_services", {})
    apt_simulate = payload.get("apt_simulate", {})
    reboot_stat = payload.get("reboot_stat", {})

    # 1. Build context
    ctx_dict = {
        "system": {
            "hostname": ansible_facts.get("hostname", ""),
            "ip": ansible_facts.get("default_ipv4", {}).get("address", "N/A"),
            "kernel": ansible_facts.get("kernel", "unknown"),
            "uptime_days": to_int(ansible_facts.get("uptime_seconds", 0)) // 86400,
            "load_avg": (ansible_facts.get("loadavg") or {"15m": 0}).get("15m", 0),
            "memory": {
                "total_mb": ansible_facts.get("memtotal_mb", 0),
                "free_mb": ansible_facts.get("memfree_mb", 0),
                "used_pct": round(((ansible_facts.get("memtotal_mb", 1) - ansible_facts.get("memfree_mb", 0)) / ansible_facts.get("memtotal_mb", 1)) * 100, 1) if ansible_facts.get("memtotal_mb", 0) > 0 else 0,
            },
            "swap": {
                "total_mb": ansible_facts.get("swaptotal_mb", 0),
                "used_pct": round(((ansible_facts.get("swaptotal_mb", 1) - ansible_facts.get("swapfree_mb", 0)) / ansible_facts.get("swaptotal_mb", 1)) * 100, 1) if ansible_facts.get("swaptotal_mb", 0) > 0 else 0,
            },
            "services": {
                "failed_count": len(safe_list(failed_services_raw.get("stdout_lines"))),
                "failed_list": safe_list(failed_services_raw.get("stdout_lines")),
            },
            "disks": build_storage_inventory(mounts),
        },
        "updates": {
            "pending_count": parse_apt_simulate_output(apt_simulate.get("stdout_lines", [])),
            "reboot_pending": bool(reboot_stat.get("stat", {}).get("exists", False)),
        },
        "security": {
            "users": build_user_inventory(getent_passwd, shadow_raw.get("stdout_lines", []), to_int(ansible_facts.get("date_time", {}).get("epoch", 0))),
            "ssh_config": parse_sshd_config(sshd_raw.get("stdout_lines", [])),
            "file_stats": {
                res["item"]: res.get("stat", {}) 
                for res in safe_list(payload.get("file_stats", {}).get("results", []))
                if isinstance(res, dict) and "item" in res
            },
            "world_writable_files": safe_list(payload.get("world_writable", {}).get("stdout_lines")),
        }
    }

    # 2. Alerts
    alerts = []
    
    # Memory Alert
    mem_used = ctx_dict["system"]["memory"]["used_pct"]
    mem_alert = build_threshold_alert(
        mem_used, 98.0, config.get("ubuntu_memory_warning_pct", 85.0),
        "capacity", f"Memory Saturation: {mem_used}%",
        detail={"total_mb": ctx_dict["system"]["memory"]["total_mb"]}
    )
    if mem_alert:
        alerts.append(mem_alert)

    # Disk Alerts
    for disk in ctx_dict["system"]["disks"]:
        disk_alert = build_threshold_alert(
            disk["used_pct"], 95.0, config.get("ubuntu_storage_warning_pct", 80.0),
            "capacity", f"Storage Saturation on {disk['mount']}: {disk['used_pct']}%",
            detail={"device": disk["device"], "mount": disk["mount"]},
            direction="gt",
            value_key="usage_pct"
        )
        if disk_alert:
            alerts.append(disk_alert)

    # Generic Policy Checks
    checks = [
        {
            "condition": ctx_dict["system"]["services"]["failed_count"] > 0,
            "severity": "CRITICAL",
            "category": "availability",
            "message": f"{ctx_dict['system']['services']['failed_count']} systemd service(s) failed",
            "detail": {"failed_list": ctx_dict["system"]["services"]["failed_list"]}
        },
        {
            "condition": ctx_dict["updates"]["reboot_pending"],
            "severity": "WARNING",
            "category": "patching",
            "message": "System requires a reboot to apply kernel or security updates"
        },
        {
            "condition": ctx_dict["system"]["uptime_days"] > 180,
            "severity": "WARNING",
            "category": "maintenance",
            "message": "Uptime Policy Violation: Server has not rebooted in over 6 months"
        }
    ]
    alerts = append_alerts(alerts, build_alerts(checks))

    rollups = compute_audit_rollups(alerts)

    # DEBUG: print alerts
    for a in alerts:
        if not isinstance(a.get("affected_items"), list):
            print(f"BAD ALERT: {a}")

    return LinuxAuditModel(
        metadata=MetadataModel(
            audit_type="linux_system",
            timestamp=collected_at,
        ),
        health=rollups["health"],
        summary=SummaryModel.model_validate(rollups["summary"]),
        alerts=[AlertModel.model_validate(a) for a in alerts],
        ubuntu_ctx=LinuxContext.model_validate(ctx_dict),
        linux_system={
            "health": rollups["health"],
            "summary": rollups["summary"],
            "alerts": alerts,
            "data": ctx_dict
        }
    )


