# internal.vmware/plugins/filter/discovery.py
# Thin wrapper — business logic lives in module_utils/discovery.py

import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import (
        load_local_module_utils,
        load_module_utils,
    )
except ImportError:
    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_module_utils = _loader_mod.load_module_utils
    load_local_module_utils = _loader_mod.load_local_module_utils

# Re-export discovery_result from core (used by playbooks via this filter)
_norm = load_module_utils(__file__, "normalization", "normalization.py")
discovery_result = _norm.result_envelope
parse_json_command_result = _norm.parse_json_command_result

# Load all business logic from local module_utils
_mod = load_local_module_utils(__file__, "discovery", "discovery.py")

# Module-level re-exports (tests do cls.module.some_function)
seed_vmware_ctx = _mod.seed_vmware_ctx
append_vmware_ctx_alert = _mod.append_vmware_ctx_alert
mark_vmware_ctx_unreachable = _mod.mark_vmware_ctx_unreachable
build_discovery_export_payload = _mod.build_discovery_export_payload
normalize_compute_inventory = _mod.normalize_compute_inventory
normalize_datastores = _mod.normalize_datastores
normalize_appliance_backup_result = _mod.normalize_appliance_backup_result
normalize_appliance_health_result = _mod.normalize_appliance_health_result
normalize_compute_result = _mod.normalize_compute_result
normalize_storage_result = _mod.normalize_storage_result
analyze_workload_vms = _mod.analyze_workload_vms
normalize_workload_result = _mod.normalize_workload_result
normalize_datacenters_result = _mod.normalize_datacenters_result
parse_alarm_script_output = _mod.parse_alarm_script_output
parse_esxi_ssh_facts = _mod.parse_esxi_ssh_facts
normalize_alarm_result = _mod.normalize_alarm_result
enrich_snapshots = _mod.enrich_snapshots
snapshot_owner_map = _mod.snapshot_owner_map
snapshot_no_datacenter_result = _mod.snapshot_no_datacenter_result
normalize_snapshots_result = _mod.normalize_snapshots_result
build_discovery_ctx = _mod.build_discovery_ctx


class FilterModule:
    def filters(self):
        return {
            "normalize_compute_inventory": normalize_compute_inventory,
            "normalize_datastores": normalize_datastores,
            "normalize_appliance_backup_result": normalize_appliance_backup_result,
            "normalize_appliance_health_result": normalize_appliance_health_result,
            "normalize_compute_result": normalize_compute_result,
            "normalize_storage_result": normalize_storage_result,
            "analyze_workload_vms": analyze_workload_vms,
            "normalize_workload_result": normalize_workload_result,
            "discovery_result": discovery_result,
            "normalize_datacenters_result": normalize_datacenters_result,
            "parse_alarm_script_output": parse_alarm_script_output,
            "parse_esxi_ssh_facts": parse_esxi_ssh_facts,
            "normalize_alarm_result": normalize_alarm_result,
            "enrich_snapshots": enrich_snapshots,
            "snapshot_owner_map": snapshot_owner_map,
            "snapshot_no_datacenter_result": snapshot_no_datacenter_result,
            "normalize_snapshots_result": normalize_snapshots_result,
            "build_discovery_ctx": build_discovery_ctx,
            "build_discovery_export_payload": build_discovery_export_payload,
            "seed_vmware_ctx": seed_vmware_ctx,
            "append_vmware_ctx_alert": append_vmware_ctx_alert,
            "mark_vmware_ctx_unreachable": mark_vmware_ctx_unreachable,
        }
