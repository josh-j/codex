import sys
import json
import re

from typing import Any


def get_vms_list(vms_info: dict[str, Any], exclude_patterns: list[str] | None = None) -> list[dict[str, Any]]:
    """Normalize VM list with enriched data from tags and attributes, filtering by name patterns."""
    if not isinstance(vms_info, dict):
        return []

    raw_vms = vms_info.get("virtual_machines", [])
    if not isinstance(raw_vms, list):
        return []

    exclude_re = None
    if exclude_patterns:
        # If it's a string (e.g. from YAML formatting), try to parse it as a list
        if isinstance(exclude_patterns, str):
            try:
                # If it looks like a Python list representation, parse it
                if exclude_patterns.startswith("[") and exclude_patterns.endswith("]"):
                    import ast

                    exclude_patterns = ast.literal_eval(exclude_patterns)
                else:
                    # Single pattern string
                    exclude_patterns = [exclude_patterns]
            except Exception:
                exclude_patterns = [exclude_patterns]

        if isinstance(exclude_patterns, list):
            # Join patterns into a single OR regex for performance
            try:
                pattern_str = "|".join(f"({p})" for p in exclude_patterns if p)
                if pattern_str:
                    exclude_re = re.compile(pattern_str, re.IGNORECASE)
            except re.error:
                # Fallback if patterns are mangled
                exclude_re = None

    normalized_vms = []
    for item in raw_vms:
        if not isinstance(item, dict):
            continue

        guest_name = item.get("guest_name", "Unknown")

        # Skip infrastructure VMs
        if exclude_re and exclude_re.search(guest_name):
            continue

        # Parse tags
        tags: list[dict[str, Any]] = item.get("tags", [])
        owner_tag_obj: dict[str, Any] = next((t for t in tags if t.get("category_name") == "Owner"), {})
        backup_tag_obj: dict[str, Any] = next((t for t in tags if t.get("category_name") == "Backup Schedule"), {})
        email_tag_obj: dict[str, Any] = next(
            (t for t in tags if t.get("category_name") in ("Owner Email", "OwnerEmail")), {}
        )

        # Parse attributes
        attributes = item.get("attributes", {})

        # Robust extraction for Owner Email
        owner_email = (
            attributes.get("Owner Email")
            or attributes.get("OwnerEmail")
            or attributes.get("owner_email")
            or email_tag_obj.get("name")
            or ""
        )

        # Robust extraction for Last Backup
        last_backup = (
            attributes.get("Last Dell PowerProtect Backup")
            or attributes.get("Last Backup")
            or attributes.get("LastBackup")
            or attributes.get("backup_date")
            or ""
        )

        vm_normalized = {
            "guest_name": guest_name,
            "uuid": item.get("uuid", ""),
            "power_state": item.get("power_state", "Unknown"),
            "guest_os": item.get("guest_fullname", "Unknown"),
            "tools_status": item.get("tools_status", "unknown"),
            "esxi_host": item.get("esxi_hostname", "N/A"),
            "cluster": item.get("cluster", "N/A"),
            "datacenter": item.get("datacenter", "N/A"),
            "ip_address": item.get("ip_address", "N/A"),
            "tags": tags,
            "backup_info": last_backup,
            "backup_schedule": backup_tag_obj.get("name", "None"),
            "owner_name": attributes.get("Owner Name", attributes.get("OwnerName", "")),
            "owner_email": owner_email,
            "owner_tag": owner_tag_obj.get("name", ""),
            "owner_description": owner_tag_obj.get("description", ""),
            "allocated": {"cpu": item.get("num_cpu", 0), "memory": item.get("memory_mb", 0)},
        }
        normalized_vms.append(vm_normalized)

    return normalized_vms


if __name__ == "__main__":
    try:
        # Schema engine passes: {"fields": {...}, "args": {...}} via stdin
        input_data = json.load(sys.stdin)
        fields = input_data.get("fields", {})
        args = input_data.get("args", {})

        vms_info = fields.get("vms_info_raw", {})
        exclude_patterns = args.get("exclude_patterns", [])

        result = get_vms_list(vms_info, exclude_patterns=exclude_patterns)
        print(json.dumps(result))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(2)
