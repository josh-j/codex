# internal.windows/plugins/module_utils/audit.py
# Pure business logic for Windows audit structure builders and export.
# No Ansible dependencies — imported by the thin filter wrapper.

import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import load_module_utils
except ImportError:
    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_module_utils = _loader_mod.load_module_utils

_prim = load_module_utils(__file__, "reporting_primitives", "reporting_primitives.py")
safe_list = _prim.safe_list


def _as_dict(value):
    return dict(value) if isinstance(value, dict) else {}


def build_app_inventory_structure(
    startup_delay=0,
    skip_startup_delay=False,
    remote_scripts_path=r"C:\Temp\AnsibleScripts",
    local_report_path="./reports",
    export_csv=True,
):
    return {
        "config": {
            "startup_delay": int(startup_delay or 0),
            "skip_startup_delay": bool(skip_startup_delay),
            "remote_scripts_path": str(remote_scripts_path),
            "local_report_path": str(local_report_path),
            "export_csv": bool(export_csv),
        },
        "services": {"ccmexec_running": False},
        "applications": {
            "configmgr_apps": [],
            "installed_apps": [],
            "metrics": {},
        },
    }


def build_configmgr_update_structure(
    startup_delay=0,
    skip_startup_delay=False,
    remote_scripts_path=r"C:\Temp\AnsibleScripts",
    update_log_directory=r"C:\Temp\ConfigMgrLogs",
    excluded_apps=None,
    force_update=False,
    allow_reboot=False,
    enforce_preference="Immediate",
    update_priority="Normal",
    cleanup_old_logs=True,
    export_csv=True,
):
    return {
        "config": {
            "startup_delay": int(startup_delay or 0),
            "skip_startup_delay": bool(skip_startup_delay),
            "remote_scripts_path": str(remote_scripts_path),
            "update_log_directory": str(update_log_directory),
            "excluded_apps": list(excluded_apps or []),
            "force_update": bool(force_update),
            "allow_reboot": bool(allow_reboot),
            "enforce_preference": str(enforce_preference),
            "update_priority": str(update_priority),
            "cleanup_old_logs": bool(cleanup_old_logs),
            "export_csv": bool(export_csv),
        },
        "services": {"ccmexec_running": False},
        "applications": {
            "apps_to_update": [],
            "excluded_apps": [],
            "already_current": [],
            "total_apps": 0,
            "summary": {},
        },
        "updates": {
            "results": [],
            "logs": [],
        },
    }


def set_ccmexec_running(windows_ctx, running):
    out = dict(_as_dict(windows_ctx))
    out["services"] = dict(out.get("services") or {})
    out["services"]["ccmexec_running"] = bool(running)
    return out


def merge_applications(windows_ctx, apps_data):
    out = dict(_as_dict(windows_ctx))
    apps = dict(out.get("applications") or {})
    apps.update(_as_dict(apps_data))
    out["applications"] = apps
    return out


def compute_application_metrics(windows_ctx):
    out = dict(_as_dict(windows_ctx))
    apps = dict(out.get("applications") or {})
    apps["metrics"] = {
        "configmgr_count": len(safe_list(apps.get("configmgr_apps"))),
        "installed_count": len(safe_list(apps.get("installed_apps"))),
    }
    out["applications"] = apps
    return out


def set_update_results(windows_ctx, results):
    out = dict(_as_dict(windows_ctx))
    out["updates"] = dict(out.get("updates") or {})
    out["updates"]["results"] = safe_list(results)
    return out


def set_empty_applications(windows_ctx):
    out = dict(_as_dict(windows_ctx))
    out["applications"] = {
        "configmgr_apps": [],
        "installed_apps": [],
        "metrics": {"configmgr_count": 0, "installed_count": 0},
    }
    return out


def set_empty_configmgr_update_state(windows_ctx):
    out = dict(_as_dict(windows_ctx))
    out["applications"] = {
        "apps_to_update": [],
        "excluded_apps": [],
        "already_current": [],
        "total_apps": 0,
        "summary": {},
    }
    out["updates"] = {"results": [], "logs": []}
    return out


def build_windows_audit_export_payload(windows_ctx, audit_failed=False):
    ctx = copy.deepcopy(_as_dict(windows_ctx))
    services = _as_dict(ctx.get("services"))
    apps = _as_dict(ctx.get("applications"))
    updates = _as_dict(ctx.get("updates"))
    results = safe_list(updates.get("results"))
    failed_updates = [r for r in results if isinstance(r, dict) and bool(r.get("failed", False))]

    summary = {
        "applications": {
            "configmgr_count": len(safe_list(apps.get("configmgr_apps"))),
            "installed_count": len(safe_list(apps.get("installed_apps"))),
            "apps_to_update_count": len(safe_list(apps.get("apps_to_update"))),
            "total_apps": int(apps.get("total_apps") or 0),
        },
        "updates": {
            "results_count": len(results),
            "failed_count": len(failed_updates),
        },
        "services": {
            "ccmexec_running": bool(services.get("ccmexec_running", False)),
        },
    }

    if bool(audit_failed):
        health = "CRITICAL"
    elif failed_updates:
        health = "WARNING"
    elif "ccmexec_running" in services and not bool(services.get("ccmexec_running")):
        health = "WARNING"
    else:
        health = "HEALTHY"

    return {
        "audit_type": "windows_audit",
        "audit_failed": bool(audit_failed),
        "health": health,
        "summary": summary,
        "alerts": safe_list(ctx.get("alerts")),
        "check_metadata": {
            "engine": "ansible-ncs-windows",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "windows_audit": ctx,
    }
