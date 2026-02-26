# internal.windows/plugins/filter/audit.py
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
build_app_inventory_structure = _mod.build_app_inventory_structure
build_configmgr_update_structure = _mod.build_configmgr_update_structure
set_ccmexec_running = _mod.set_ccmexec_running
merge_applications = _mod.merge_applications
compute_application_metrics = _mod.compute_application_metrics
set_update_results = _mod.set_update_results
set_empty_applications = _mod.set_empty_applications
set_empty_configmgr_update_state = _mod.set_empty_configmgr_update_state
build_windows_audit_export_payload = _mod.build_windows_audit_export_payload
safe_list = _mod.safe_list


class FilterModule:
    def filters(self):
        return {
            "build_app_inventory_structure": build_app_inventory_structure,
            "build_configmgr_update_structure": build_configmgr_update_structure,
            "set_ccmexec_running": set_ccmexec_running,
            "merge_applications": merge_applications,
            "compute_application_metrics": compute_application_metrics,
            "set_update_results": set_update_results,
            "set_empty_applications": set_empty_applications,
            "set_empty_configmgr_update_state": set_empty_configmgr_update_state,
            "build_windows_audit_export_payload": build_windows_audit_export_payload,
        }
