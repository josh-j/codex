# collections/ansible_collections/internal/vmware/plugins/filter/snapshot.py

import importlib.util
import re
from pathlib import Path
from urllib.parse import unquote

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
to_float = _prim.to_float
safe_list = _prim.safe_list


def enrich_snapshots(snapshots, owner_map=None):
    """
    Enriches age-filtered snapshot dicts with vmware-specific fields.
    Expects items already processed by internal.core.filter_by_age.

    Normalises snapshot_name (urldecode), resolves owner_email from
    owner_map, and casts size_gb to float.

    Args:
        snapshots:  list - dicts from filter_by_age output
        owner_map:  dict - {vm_name: owner_email}, optional

    Returns:
        list of enriched snapshot dicts
    """
    owner_map = dict(owner_map or {})
    results = []

    for snap in safe_list(snapshots):
        if not isinstance(snap, dict):
            continue
        vm_name = snap.get("vm_name", "unknown")
        results.append(
            {
                **snap,
                "vm_name": vm_name,
                "snapshot_name": unquote(snap.get("name", "unnamed")),
                "size_gb": to_float(snap.get("size_gb", 0)),
                "owner_email": owner_map.get(vm_name, ""),
            }
        )

    return results


def snapshot_no_datacenter_result(
    value=None, datacenter=None, collected_at=None, reason=None
):
    """
    Filter-safe: can be called as:
      '' | internal.vmware.snapshot_no_datacenter_result(_snap_dc_name, _collected_at)

    Jinja filter calling convention passes the piped value as the first arg.

    Args:
      value:        piped value from Jinja (usually unused)
      datacenter:   datacenter name (optional)
      collected_at: controller timestamp (optional)
      reason:       optional override message

    Returns:
      dict compatible with normalize_snapshots_result-style consumers:
        - all: []
        - aged: []
        - summary: { ... }
        - collected_at: ...
        - skipped: True
    """
    # Back-compat / leniency:
    # If caller used the older one-arg form and accidentally passed collected_at as the 2nd arg,
    # detect ISO-ish timestamp and shift it into collected_at.
    if collected_at is None and isinstance(datacenter, str) and datacenter:
        if re.match(r"^\d{4}-\d{2}-\d{2}T", datacenter):
            collected_at = datacenter
            datacenter = None

    return {
        "skipped": True,
        "reason": reason
        or "No datacenter discovered; snapshots discovery was skipped.",
        "datacenter": datacenter or "",
        "collected_at": collected_at or "",
        # Match the common normalize_snapshots_result shape (lists + summary)
        "all": [],
        "aged": [],
        "summary": {
            "total": 0,
            "violations": 0,
            "old_count": 0,
            "large_count": 0,
            "oldest_days": 0,
            "largest_gb": 0.0,
        },
    }


class FilterModule:
    def filters(self):
        return {
            "enrich_snapshots": enrich_snapshots,
            "snapshot_no_datacenter_result": snapshot_no_datacenter_result,
        }
