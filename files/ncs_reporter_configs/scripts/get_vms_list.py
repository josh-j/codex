import json
import re
import sys
from datetime import datetime
from typing import Any


def _parse_backup_time(raw_backup: str) -> str:
    """Parse EndTime or StartTime from Dell PowerProtect backup attribute.

    Raw format:
        "Backup Server=xxx, Policy=xxx, Stage=xxx,
         StartTime=2026-03-08T16:00:13Z, EndTime=2026-03-08T16:31:40Z"

    Returns "YYYY-MM-DD HH:MM UTC" or empty string.
    """
    if not raw_backup:
        return ""
    for time_key in ("EndTime", "StartTime"):
        match = re.search(rf"{time_key}=(\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z?)", raw_backup)
        if match:
            raw_ts = match.group(1)
            try:
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M UTC")
            except (ValueError, TypeError):
                return raw_ts
    return ""


def _format_tags_display(tags: list[dict[str, Any]]) -> str:
    """Format all VM tags as 'Category: Name' comma-separated string."""
    if not isinstance(tags, list):
        return ""
    parts = []
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        cat = str(tag.get("category_name", "")).strip()
        name = str(tag.get("name", "")).strip()
        if cat and name:
            parts.append(f"{cat}: {name}")
        elif name:
            parts.append(name)
    return ", ".join(parts)


def get_vms_list(vms_info: dict[str, Any], exclude_patterns: list[str] | None = None) -> list[dict[str, Any]]:
    """Normalize VM list with enriched data from tags and attributes, filtering by name patterns."""
    if not isinstance(vms_info, dict):
        return []

    raw_vms = vms_info.get("virtual_machines", [])
    if not isinstance(raw_vms, list):
        return []

    exclude_re = None
    if exclude_patterns:
        if isinstance(exclude_patterns, str):
            try:
                if exclude_patterns.startswith("[") and exclude_patterns.endswith("]"):
                    import ast

                    exclude_patterns = ast.literal_eval(exclude_patterns)
                else:
                    exclude_patterns = [exclude_patterns]
            except Exception:
                exclude_patterns = [exclude_patterns]

        if isinstance(exclude_patterns, list):
            try:
                pattern_str = "|".join(f"({p})" for p in exclude_patterns if p)
                if pattern_str:
                    exclude_re = re.compile(pattern_str, re.IGNORECASE)
            except re.error:
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

        # Robust extraction for Last Backup (raw string)
        last_backup_raw = (
            attributes.get("Last Dell PowerProtect Backup")
            or attributes.get("Last Backup")
            or attributes.get("LastBackup")
            or attributes.get("backup_date")
            or ""
        )

        # Parse backup timestamp from raw Dell PowerProtect string
        backup_last_time = _parse_backup_time(last_backup_raw)

        # Backup schedule tag name
        backup_tag = backup_tag_obj.get("name", "")

        # All tags formatted for display
        tags_display = _format_tags_display(tags)

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
            "tags_display": tags_display,
            "backup_tag": backup_tag,
            "backup_last_time": backup_last_time,
            "backup_info": last_backup_raw,
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
        input_data = json.load(sys.stdin)
        fields = input_data.get("fields", {})
        args = input_data.get("args", {})

        vms_info = fields.get("vms_info_raw", {})
        exclude_patterns = args.get("exclude_patterns", [])

        result = get_vms_list(vms_info, exclude_patterns=exclude_patterns)
        print(json.dumps(result))
    except Exception as e:
        sys.stderr.write(f"Error: {e!s}\n")
        sys.exit(2)
