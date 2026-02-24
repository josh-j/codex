# internal.vmware/plugins/filter/snapshot.py

from urllib.parse import unquote


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
    owner_map = owner_map or {}
    results = []

    for snap in snapshots:
        vm_name = snap.get("vm_name", "unknown")
        results.append(
            {
                **snap,
                "vm_name": vm_name,
                "snapshot_name": unquote(snap.get("name", "unnamed")),
                "size_gb": float(snap.get("size_gb", 0)),
                "owner_email": owner_map.get(vm_name, ""),
            }
        )

    return results


class FilterModule(object):
    def filters(self):
        return {"enrich_snapshots": enrich_snapshots}
