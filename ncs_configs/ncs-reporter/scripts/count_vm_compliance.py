"""Count powered-on VMs missing owner email, backup tag, or backup record.

Metrics:
    missing_owner      — no Owner Email attribute
    missing_backup_tag — no Backup Schedule tag
    missing_backup     — no recorded backup (no backup_last_time)
"""

import json
import sys
from typing import Any


def count_vm_compliance(virtual_machines: list[dict[str, Any]], metric: str) -> int:
    if not isinstance(virtual_machines, list):
        return 0

    count = 0
    for vm in virtual_machines:
        if not isinstance(vm, dict):
            continue
        if vm.get("power_state") != "poweredOn":
            continue

        if metric == "missing_owner":
            if not vm.get("owner_email", "").strip():
                count += 1
        elif metric == "missing_backup_tag":
            if not vm.get("backup_tag", "").strip():
                count += 1
        elif metric == "missing_backup":
            if not vm.get("backup_last_time", "").strip():
                count += 1

    return count


if __name__ == "__main__":
    try:
        input_data = json.load(sys.stdin)
        fields = input_data.get("fields", {})
        args = input_data.get("args", {})

        vms = fields.get("virtual_machines", [])
        metric = args.get("metric", "missing_owner")

        result = count_vm_compliance(vms, metric)
        print(json.dumps(result))
    except Exception as e:
        sys.stderr.write(f"Error: {e!s}\n")
        sys.exit(2)
