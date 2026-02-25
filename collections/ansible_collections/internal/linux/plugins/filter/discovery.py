try:
    from ansible_collections.internal.core.plugins.module_utils.loader import load_module_utils
except ImportError:
    import importlib.util
    from pathlib import Path

    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_module_utils = _loader_mod.load_module_utils

_prim = load_module_utils(__file__, "reporting_primitives", "reporting_primitives.py")
_to_int = _prim.to_int
_to_float = _prim.to_float
safe_list = _prim.safe_list


def build_disk_inventory(mounts):
    results = []
    for mount in safe_list(mounts):
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
    shadow_lines = safe_list(shadow_lines)
    epoch_days = _to_int(epoch_seconds, 0) // 86400

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
        # parts[2] is last_change in /etc/shadow
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
    for line in safe_list(stdout_lines):
        line = str(line or "").strip()
        if not line or line.startswith("#"):
            continue
        # Split on first whitespace, but normalize it first
        import re

        parts = re.split(r"\s+", line, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            # Strip trailing comments from value
            val = parts[1].split("#", 1)[0].strip()
            out[parts[0]] = val
    return out


def collect_existing_file_stats(results):
    out = {}
    for res in safe_list(results):
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

    for line in reversed(safe_list(stdout_lines)):
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
