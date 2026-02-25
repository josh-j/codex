from typing import Any

"""Declarative CSV export definitions per platform."""

CSV_DEFINITIONS: list[dict[str, Any]] = [
    {
        "report_name": "windows_configmgr_apps",
        "headers": ["Server", "App Name", "Version", "Publisher", "Install State"],
        "data_path": "windows_ctx.applications.configmgr_apps",
        "sort_by": "App Name",
        "platform": "windows",
    },
    {
        "report_name": "configmgr_apps_to_update",
        "headers": ["Server", "App Name", "Current Version", "Target Version", "Update Reason"],
        "data_path": "windows_ctx.applications.apps_to_update",
        "sort_by": "App Name",
        "platform": "windows",
    },
]


def get_definitions(platform: str) -> list[dict[str, Any]]:
    """Return CSV definitions for a given platform."""
    return [d for d in CSV_DEFINITIONS if d["platform"] == platform]


def resolve_data_path(bundle: dict[str, Any], data_path: str) -> list[Any]:
    """Walk a dot-separated path into a nested dict, returning [] on miss."""
    obj: Any = bundle
    for segment in data_path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(segment)
        else:
            return []
    return obj if isinstance(obj, list) else []
