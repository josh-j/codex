# internal.vmware/plugins/filter/audit.py
# Thin wrapper — business logic lives in module_utils/audit.py

import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import (
        load_local_module_utils,
    )
except ImportError:
    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_local_module_utils = _loader_mod.load_local_module_utils

# Load all business logic from local module_utils
_mod = load_local_module_utils(__file__, "audit", "audit.py")

# Module-level re-exports (tests do cls.module.some_function)
build_audit_export_payload = _mod.build_audit_export_payload
audit_health_alerts = _mod.audit_health_alerts
audit_alarm_alerts = _mod.audit_alarm_alerts
audit_cluster_configuration_alerts = _mod.audit_cluster_configuration_alerts
audit_storage_rollup_alerts = _mod.audit_storage_rollup_alerts
audit_storage_object_alerts = _mod.audit_storage_object_alerts
audit_snapshot_alerts = _mod.audit_snapshot_alerts
audit_tools_alerts = _mod.audit_tools_alerts
audit_resource_rollup = _mod.audit_resource_rollup
attach_audit_utilization = _mod.attach_audit_utilization
attach_audit_results = _mod.attach_audit_results
build_owner_notification_context = _mod.build_owner_notification_context

# Core re-exports used by playbooks via this filter
append_alerts = _mod.append_alerts
compute_audit_rollups = _mod.compute_audit_rollups
canonical_severity = _mod.canonical_severity


class FilterModule:
    def filters(self):
        return {
            "build_audit_export_payload": build_audit_export_payload,
            "audit_health_alerts": audit_health_alerts,
            "audit_alarm_alerts": audit_alarm_alerts,
            "audit_cluster_configuration_alerts": audit_cluster_configuration_alerts,
            "audit_storage_rollup_alerts": audit_storage_rollup_alerts,
            "audit_storage_object_alerts": audit_storage_object_alerts,
            "audit_snapshot_alerts": audit_snapshot_alerts,
            "audit_tools_alerts": audit_tools_alerts,
            "audit_resource_rollup": audit_resource_rollup,
            "attach_audit_utilization": attach_audit_utilization,
            "attach_audit_results": attach_audit_results,
            "append_alerts": append_alerts,
            "compute_audit_rollups": compute_audit_rollups,
            "build_owner_notification_context": build_owner_notification_context,
        }
