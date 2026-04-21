#!/usr/bin/env python3
"""Build a per-owner VMware compliance digest from collected raw_vm.yaml bundles.

Reads every `<platform_root>/vmware/vm/*/raw_vm.yaml`, classifies each VM via
the same `get_vms_list()` function the reporter uses, then groups findings by
VM owner email. Emits a JSON document consumed by `owner_digest.yml`:

    {
      "owner_issues": {
        "alice@example.com": {
          "vcenters": ["vc-prod-01"],
          "no_backup":        [...vm dicts...],
          "no_backup_tags":   [...],
          "overdue_backup":   [...],
          "no_owner_email":   [...],    (always empty for this owner)
          "missing_owner_desc": [...],
          "aged_snapshots":   [...snapshot dicts...],
          "powered_off":      [...]
        },
        ...
      },
      "orphans": {
        "no_owner_email":   [...],
        "missing_owner_desc": [...]
      }
    }

Rows for `no_owner_email` have no deliverable address, so they're bucketed into
`orphans` for the playbook to report in a summary (not emailed).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_EMAIL_RE = re.compile(r"^.+@.+\..+$")


def _find_bundles(platform_root: Path) -> list[Path]:
    return sorted((platform_root / "vmware" / "vm").glob("*/raw_vm.yaml"))


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _classify(vms_info_raw: dict[str, Any], exclude_patterns: list[str], scripts_dir: Path) -> list[dict[str, Any]]:
    """Defer to the reporter's get_vms_list() so classification stays in one place."""
    sys.path.insert(0, str(scripts_dir))
    try:
        import get_vms_list  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return get_vms_list.get_vms_list(vms_info_raw, exclude_patterns=exclude_patterns)


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _aged_snapshots_with_owner(
    snapshots_raw: list[dict[str, Any]],
    age_days: int,
    vms: list[dict[str, Any]],
    reference: datetime,
) -> list[dict[str, Any]]:
    vm_owners = {vm["guest_name"]: vm.get("owner_email", "") for vm in vms if vm.get("guest_name")}
    aged: list[dict[str, Any]] = []
    for snap in snapshots_raw:
        if not isinstance(snap, dict):
            continue
        dt = _parse_iso(str(snap.get("creation_time") or snap.get("createTime") or ""))
        if dt is None:
            continue
        days_old = (reference - dt).days
        if days_old < age_days:
            continue
        enriched = dict(snap)
        enriched["days_old"] = days_old
        enriched["owner_email"] = vm_owners.get(snap.get("vm_name", ""), "")
        aged.append(enriched)
    return aged


def _owner_bucket() -> dict[str, Any]:
    return {
        "vcenters": [],
        "no_backup": [],
        "no_backup_tags": [],
        "overdue_backup": [],
        "missing_owner_desc": [],
        "aged_snapshots": [],
        "powered_off": [],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--platform-root", required=True, type=Path)
    ap.add_argument("--scripts-dir", required=True, type=Path)
    ap.add_argument("--age-days", type=int, default=7)
    ap.add_argument("--notify-powered-off", action="store_true")
    args = ap.parse_args(argv)

    owner_issues: dict[str, dict[str, Any]] = {}
    orphans = {"no_owner_email": [], "missing_owner_desc": []}

    bundles = _find_bundles(args.platform_root)
    if not bundles:
        sys.stderr.write(f"no raw_vm.yaml bundles under {args.platform_root}/vmware/vm\n")
        return 1

    for bundle_path in bundles:
        bundle = _load_yaml(bundle_path)
        data = bundle.get("data") or bundle
        vcenter = bundle.get("metadata", {}).get("host") or bundle_path.parent.name
        vms_info_raw = data.get("vms_info_raw") or {"virtual_machines": data.get("virtual_machines", [])}
        infra_patterns = data.get("infra_patterns", [])
        vms = _classify(vms_info_raw, infra_patterns, args.scripts_dir)

        snapshots_raw = data.get("snapshots_raw", [])
        aged = _aged_snapshots_with_owner(snapshots_raw, args.age_days, vms, datetime.now(tz=timezone.utc))

        for vm in vms:
            owner = (vm.get("owner_email") or "").strip()
            has_email = bool(_EMAIL_RE.match(owner))
            if not has_email:
                orphans["no_owner_email"].append({"vcenter": vcenter, **vm})
            if vm.get("owner_tag") and not vm.get("owner_description"):
                entry = {"vcenter": vcenter, **vm}
                if has_email:
                    owner_issues.setdefault(owner, _owner_bucket())["missing_owner_desc"].append(entry)
                else:
                    orphans["missing_owner_desc"].append(entry)
            if not has_email:
                continue

            bucket = owner_issues.setdefault(owner, _owner_bucket())
            if vcenter not in bucket["vcenters"]:
                bucket["vcenters"].append(vcenter)
            if vm.get("backup_never"):
                bucket["no_backup"].append({"vcenter": vcenter, **vm})
            if vm.get("backup_expected_days", -1) == -1:
                bucket["no_backup_tags"].append({"vcenter": vcenter, **vm})
            if vm.get("backup_overdue"):
                bucket["overdue_backup"].append({"vcenter": vcenter, **vm})
            if args.notify_powered_off and vm.get("power_state") == "poweredOff":
                bucket["powered_off"].append({"vcenter": vcenter, **vm})

        for snap in aged:
            owner = (snap.get("owner_email") or "").strip()
            if not _EMAIL_RE.match(owner):
                continue
            bucket = owner_issues.setdefault(owner, _owner_bucket())
            if vcenter not in bucket["vcenters"]:
                bucket["vcenters"].append(vcenter)
            bucket["aged_snapshots"].append({"vcenter": vcenter, **snap})

    json.dump({"owner_issues": owner_issues, "orphans": orphans}, sys.stdout, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
