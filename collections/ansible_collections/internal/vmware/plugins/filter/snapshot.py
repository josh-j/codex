# internal.vmware/plugins/filter/snapshot.py

import importlib.util
from pathlib import Path
from urllib.parse import unquote

try:
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        safe_list,
        to_float,
    )
except ImportError:
    _helper_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location("internal_core_reporting_primitives", _helper_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    to_float = _mod.to_float
    safe_list = _mod.safe_list


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


class FilterModule:
    def filters(self):
        return {"enrich_snapshots": enrich_snapshots}
