"""Compatibility facade for split reporting view-model modules."""

import importlib.util
from pathlib import Path

try:
    from .report_view_models_common import default_report_skip_keys
    from .report_view_models_linux import build_linux_fleet_view, build_linux_node_view
    from .report_view_models_site import build_site_dashboard_view
    from .report_view_models_stig import build_stig_fleet_view, build_stig_host_view
    from .report_view_models_vmware import build_vmware_fleet_view, build_vmware_node_view
except ImportError:
    _base = Path(__file__).resolve().parent

    def _load(name):
        path = _base / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"internal_core_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    _common = _load("report_view_models_common")
    _linux = _load("report_view_models_linux")
    _site = _load("report_view_models_site")
    _stig = _load("report_view_models_stig")
    _vmware = _load("report_view_models_vmware")

    default_report_skip_keys = _common.default_report_skip_keys
    build_linux_fleet_view = _linux.build_linux_fleet_view
    build_linux_node_view = _linux.build_linux_node_view
    build_site_dashboard_view = _site.build_site_dashboard_view
    build_stig_fleet_view = _stig.build_stig_fleet_view
    build_stig_host_view = _stig.build_stig_host_view
    build_vmware_fleet_view = _vmware.build_vmware_fleet_view
    build_vmware_node_view = _vmware.build_vmware_node_view


__all__ = [
    "build_linux_fleet_view",
    "build_linux_node_view",
    "build_site_dashboard_view",
    "build_stig_fleet_view",
    "build_stig_host_view",
    "build_vmware_fleet_view",
    "build_vmware_node_view",
    "default_report_skip_keys",
]
