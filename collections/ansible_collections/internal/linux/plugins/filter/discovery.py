def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_disk_inventory(mounts):
    results = []
    for mount in list(mounts or []):
        if not isinstance(mount, dict):
            continue
        device = str(mount.get("device") or "")
        if "loop" in device or "tmpfs" in device:
            continue

        size_total = _to_float(mount.get("size_total"), 0.0)
        size_available = _to_float(mount.get("size_available"), 0.0)
        used_pct = ((size_total - size_available) / size_total * 100.0) if size_total > 0 else 0.0

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


def build_user_inventory(getent_passwd, shadow_lines, epoch_seconds):
    getent_passwd = dict(getent_passwd or {})
    shadow_lines = list(shadow_lines or [])
    epoch_days = _to_int(epoch_seconds, 0) // 86400

    shadow_map = {}
    for line in shadow_lines:
        line = str(line or "")
        if ":" not in line:
            continue
        user = line.split(":", 1)[0]
        if user:
            shadow_map[user] = line

    results = []
    for user, info in getent_passwd.items():
        info = list(info or [])
        shadow = shadow_map.get(str(user), "")
        parts = shadow.split(":")
        last_change = _to_int(parts[2], 0) if len(parts) > 2 else 0
        results.append(
            {
                "name": str(user),
                "uid": info[1] if len(info) > 1 else "",
                "gid": info[2] if len(info) > 2 else "",
                "home": info[4] if len(info) > 4 else "",
                "shell": info[5] if len(info) > 5 else "",
                "password_age_days": (epoch_days - last_change) if last_change > 0 else -1,
            }
        )
    return results


def parse_sshd_config(stdout_lines):
    out = {}
    for line in list(stdout_lines or []):
        line = str(line or "")
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[0]:
            out[parts[0]] = parts[1]
    return out


def collect_existing_file_stats(results):
    out = {}
    for res in list(results or []):
        if not isinstance(res, dict):
            continue
        stat = res.get("stat")
        if not isinstance(stat, dict):
            continue
        if not bool(stat.get("exists")):
            continue
        item = res.get("item")
        if item is None:
            continue
        out[item] = stat
    return out


def parse_apt_simulate_output(stdout_lines):
    import re

    for line in reversed(list(stdout_lines or [])):
        line = str(line or "")
        match = re.search(r"(\d+)\s+upgraded,", line)
        if match:
            return _to_int(match.group(1), 0)
    return 0


class FilterModule:
    def filters(self):
        return {
            "build_disk_inventory": build_disk_inventory,
            "build_user_inventory": build_user_inventory,
            "parse_sshd_config": parse_sshd_config,
            "collect_existing_file_stats": collect_existing_file_stats,
            "parse_apt_simulate_output": parse_apt_simulate_output,
        }
