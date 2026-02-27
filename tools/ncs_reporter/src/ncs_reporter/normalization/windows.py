"""Windows-specific normalization logic for raw audit/update data."""

import logging
from typing import Any

from ncs_reporter.models.base import MetadataModel, SummaryModel, AlertModel
from ncs_reporter.models.windows import WindowsAuditModel
from ncs_reporter.alerts import compute_audit_rollups

logger = logging.getLogger(__name__)


def normalize_windows(raw_bundle: dict[str, Any], config: dict[str, Any] | None = None) -> WindowsAuditModel:
    """
    Main entry point for normalizing raw Windows data.
    """
    config = dict(config or {})

    # 1. Extract raw data
    discovery_raw = raw_bundle.get("raw_discovery") or raw_bundle.get("discovery") or raw_bundle
    logger.debug("normalize_windows: extracting payload from raw_bundle keys=%s", list(raw_bundle.keys()))
    if isinstance(discovery_raw, dict) and "data" in discovery_raw:
        payload = discovery_raw.get("data", {})
        metadata_raw = discovery_raw.get("metadata", {})
        collected_at = metadata_raw.get("timestamp", "")
    else:
        payload = discovery_raw
        collected_at = ""

    # 2. Reconstruct context
    ccm_service = payload.get("ccm_service") or {}
    ccmexec_running = ccm_service.get("state") == "running"
    if not ccmexec_running:
        logger.info("CCMExec service not running (state=%s)", ccm_service.get("state", "unknown"))

    # PowerShell script outputs are often wrapped strings
    def _parse_ps_json(val: Any) -> Any:
        if isinstance(val, dict) and "output" in val:
            # Handle Ansible's win_powershell register format
            try:
                import json
                return json.loads(val["output"][0])
            except (IndexError, json.JSONDecodeError, KeyError):
                return val
        return val

    configmgr_apps_raw = _parse_ps_json(payload.get("configmgr_apps") or {})
    installed_apps = _parse_ps_json(payload.get("installed_apps") or [])
    update_results = payload.get("update_results") or []
    
    apps_to_update = configmgr_apps_raw.get("AppsToUpdate", []) if isinstance(configmgr_apps_raw, dict) else []
    
    ctx_dict = {
        "config": config,
        "services": {
            "ccmexec_running": ccmexec_running,
        },
        "applications": {
            "configmgr_apps": configmgr_apps_raw.get("AllApps", []) if isinstance(configmgr_apps_raw, dict) else [],
            "installed_apps": installed_apps,
            "apps_to_update": apps_to_update,
            "metrics": {
                "configmgr_count": len(configmgr_apps_raw.get("AllApps", [])) if isinstance(configmgr_apps_raw, dict) else 0,
                "installed_count": len(installed_apps),
                "apps_to_update_count": len(apps_to_update),
            }
        },
        "updates": {
            "results": update_results,
        }
    }

    # 3. Generate Alerts & Summary
    alerts = []
    if not ccmexec_running:
        alerts.append({
            "severity": "WARNING",
            "category": "services",
            "message": "ConfigMgr client service (CCMExec) is not running",
            "detail": {"service_name": "CCMExec", "state": ccm_service.get("state", "unknown")}
        })

    failed_updates = [r for r in update_results if isinstance(r, dict) and bool(r.get("failed", False))]
    if failed_updates:
        alerts.append({
            "severity": "WARNING",
            "category": "patching",
            "message": f"{len(failed_updates)} ConfigMgr application updates failed",
            "detail": {"failed_updates": failed_updates}
        })

    rollups = compute_audit_rollups(alerts)
    
    summary_dict = {
        "applications": {
            "configmgr_count": len(configmgr_apps_raw.get("AllApps", [])) if isinstance(configmgr_apps_raw, dict) else 0,
            "installed_count": len(installed_apps) if isinstance(installed_apps, list) else 0,
            "apps_to_update_count": len(apps_to_update),
            "total_apps": to_int(configmgr_apps_raw.get("AllApps", 0) if isinstance(configmgr_apps_raw, dict) else 0),
        },
        "updates": {
            "results_count": len(update_results),
            "failed_count": len(failed_updates),
        },
        "services": {
            "ccmexec_running": ccmexec_running,
        },
    }
    summary_dict.update(rollups["summary"])

    return WindowsAuditModel(
        metadata=MetadataModel(
            audit_type="windows_audit",
            timestamp=collected_at,
        ),
        health=rollups["health"],
        summary=SummaryModel.model_validate(summary_dict),
        alerts=[AlertModel.model_validate(a) for a in alerts],
        windows_audit={
            "health": rollups["health"],
            "summary": summary_dict,
            "alerts": alerts,
            "data": ctx_dict,
        },
    )




def to_int(val: Any) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
