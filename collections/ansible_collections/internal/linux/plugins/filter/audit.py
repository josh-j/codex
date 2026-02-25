import copy
from datetime import datetime, timezone

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import load_filter, load_module_utils
except ImportError:
    import importlib.util
    from pathlib import Path

    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_module_utils = _loader_mod.load_module_utils
    load_filter = _loader_mod.load_filter

_prim = load_module_utils(__file__, "reporting_primitives", "reporting_primitives.py")
safe_list = _prim.safe_list

_alerts = load_filter(__file__, "alerts", "alerts.py")
compute_audit_rollups = _alerts.compute_audit_rollups


def build_system_audit_export_payload(ubuntu_ctx, ubuntu_alerts, health, summary):
    out = copy.deepcopy(dict(ubuntu_ctx or {}))
    out["audit_type"] = "system"
    out["audit_failed"] = False
    out["health"] = health
    out["alerts"] = safe_list(ubuntu_alerts)

    # Accept either:
    # - summary == {"total":..., ...}
    # - summary == {"summary": {"total":...}, "health": "..."}  (rollups dict)
    if (
        isinstance(summary, dict)
        and "summary" in summary
        and isinstance(summary.get("summary"), dict)
    ):
        summary_dict = summary["summary"]
    else:
        summary_dict = summary or {}

    out["summary"] = dict(summary_dict)

    out["check_metadata"] = {
        "engine": "ansible-ncs-linux",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return out


class FilterModule:
    def filters(self):
        return {
            "compute_audit_rollups": compute_audit_rollups,
            "build_system_audit_export_payload": build_system_audit_export_payload,
        }
