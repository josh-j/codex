# collections/ansible_collections/internal/core/plugins/filter/paths.py

import os


def _find_repo_root():
    """
    Locates the repository root by walking up from this filter's location.
    """
    cur = os.path.realpath(__file__)
    for _ in range(10):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
        if os.path.isdir(os.path.join(cur, "collections", "ansible_collections")):
            return cur
    return os.getcwd()  # Fallback to CWD


def resolve_ncs_path(config, platform, hostname=None, audit_type="system", extension="yaml"):
    """
    Central provider for all automation file paths (local and remote).
    Eliminates hardcoded path logic across roles/playbooks.
    """
    base = config.get("report_directory", "/srv/samba/reports")

    # Specialized: artifacts (local to project root)
    if platform == "artifacts":
        repo_root = _find_repo_root()
        if hostname is None:
            return f"{repo_root}/.artifacts/{audit_type}.{extension}"
        return f"{repo_root}/.artifacts/{hostname}/{audit_type}.{extension}"

    # Global Fleet Aggregates
    if platform == "fleet":
        return f"{base}/fleet/{audit_type}_fleet_state.{extension}"

    # Platform-level Reports (e.g., HTML dashboards)
    if extension == "html" and hostname is None:
        return f"{base}/platform/{platform}/{platform}_health_report.html"

    # Default: host-specific platform folder
    host = hostname or "unknown"
    return f"{base}/platform/{platform}/{host}/{audit_type}.{extension}"


class FilterModule:
    def filters(self):
        return {
            "resolve_ncs_path": resolve_ncs_path,
        }
