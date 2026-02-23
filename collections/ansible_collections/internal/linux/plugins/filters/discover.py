# collections/ansible_collections/internal/linux/plugins/filter/discover.py


def normalize_ubuntu_ctx(ansible_facts, raw):
    """
    raw: dict of raw command outputs passed from Ansible
      {
        'failed_services': list of lines,
        'shadow': list of lines,
        'sshd': list of lines,
        'file_stats': list of stat results,
        'world_writable': list of lines,
        'apt_simulate': list of lines,
        'reboot_required': bool
      }
    """
    # Disk usage
    disks = []
    for mount in ansible_facts.get("mounts", []):
        if "loop" in mount["device"] or "tmpfs" in mount["device"]:
            continue
        total = mount["size_total"]
        avail = mount["size_available"]
        disks.append(
            {
                "mount": mount["mount"],
                "device": mount["device"],
                "fstype": mount["fstype"],
                "total_gb": round(total / 1073741824, 1),
                "free_gb": round(avail / 1073741824, 1),
                "used_pct": round((total - avail) / total * 100, 1) if total > 0 else 0,
            }
        )

    # Memory
    mem_total = ansible_facts.get("memtotal_mb", 0)
    mem_free = ansible_facts.get("memfree_mb", 0)
    mem_pct = round((mem_total - mem_free) / mem_total * 100, 1) if mem_total > 0 else 0

    swap_total = ansible_facts.get("swaptotal_mb", 0)
    swap_free = ansible_facts.get("swapfree_mb", 0)
    swap_pct = (
        round((swap_total - swap_free) / swap_total * 100, 1) if swap_total > 0 else 0
    )

    # SSH config
    ssh_config = {}
    for line in raw.get("sshd", []):
        parts = line.split(" ", 1)
        if len(parts) == 2:
            ssh_config[parts[0]] = parts[1]

    # Shadow entries
    shadow_map = {}
    for line in raw.get("shadow", []):
        parts = line.split(":")
        if len(parts) > 1:
            shadow_map[parts[0]] = parts[1:]

    # Users
    epoch_days = int(ansible_facts.get("date_time", {}).get("epoch", 0)) // 86400
    users = []
    for user, info in ansible_facts.get("getent_passwd", {}).items():
        shadow_parts = shadow_map.get(user, [])
        last_change = (
            int(shadow_parts[1])
            if len(shadow_parts) > 1 and shadow_parts[1].isdigit()
            else 0
        )
        users.append(
            {
                "name": user,
                "uid": info[1],
                "gid": info[2],
                "home": info[4],
                "shell": info[5],
                "password_age_days": (epoch_days - last_change)
                if last_change > 0
                else -1,
            }
        )

    # File stats
    file_stats = {}
    for result in raw.get("file_stats", []):
        if result.get("stat", {}).get("exists"):
            file_stats[result["item"]] = result["stat"]

    # Pending updates
    upgrade_lines = [l for l in raw.get("apt_simulate", []) if "upgraded," in l]
    pending_count = int(upgrade_lines[-1].split()[0]) if upgrade_lines else 0

    return {
        "system": {
            "hostname": ansible_facts.get("hostname", ""),
            "ip": ansible_facts.get("default_ipv4", {}).get("address", "N/A"),
            "kernel": ansible_facts.get("kernel", "unknown"),
            "uptime_days": ansible_facts.get("uptime_seconds", 0) // 86400,
            "load_avg": ansible_facts.get("loadavg", {}).get("15m", 0),
            "memory": {"total_mb": mem_total, "free_mb": mem_free, "used_pct": mem_pct},
            "swap": {"total_mb": swap_total, "used_pct": swap_pct},
            "services": {
                "failed_count": len(raw.get("failed_services", [])),
                "failed_list": raw.get("failed_services", []),
            },
            "disks": disks,
        },
        "updates": {
            "pending_count": pending_count,
            "reboot_pending": raw.get("reboot_required", False),
        },
        "security": {
            "ssh_config": ssh_config,
            "shadow_entries": shadow_map,
            "users": users,
            "file_stats": file_stats,
            "world_writable_files": raw.get("world_writable", []),
        },
    }


class FilterModule(object):
    def filters(self):
        return {"normalize_ubuntu_ctx": normalize_ubuntu_ctx}
