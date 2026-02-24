import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.report_view_models import (
        build_vmware_fleet_view as _build_vmware_fleet_view,
    )
    from ansible_collections.internal.core.plugins.module_utils.report_view_models import (
        build_vmware_node_view as _build_vmware_node_view,
    )
except ImportError:
    _helper_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "report_view_models.py"
    _spec = importlib.util.spec_from_file_location("internal_core_report_view_models", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _build_vmware_fleet_view = _mod.build_vmware_fleet_view
    _build_vmware_node_view = _mod.build_vmware_node_view


def vmware_fleet_view(
    aggregated_hosts,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    return _build_vmware_fleet_view(
        aggregated_hosts,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )


def vmware_node_view(
    bundle,
    hostname=None,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    return _build_vmware_node_view(
        hostname or "unknown",
        bundle,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )


class FilterModule:
    def filters(self):
        return {
            "vmware_fleet_view": vmware_fleet_view,
            "vmware_node_view": vmware_node_view,
        }
