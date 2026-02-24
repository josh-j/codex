#!/usr/bin/env python3

import importlib.util
import sys
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.report_aggregation import (
        load_all_reports,
        write_output,
    )
    try:
        from ansible_collections.internal.vmware.plugins.module_utils.report_aggregation_adapter import (
            normalize_aggregated_report as _vmware_report_normalizer,
        )
    except ImportError:
        _vmware_report_normalizer = None
except ImportError:
    # Repo checkout fallback for local execution outside the Ansible collection loader.
    _helper_path = (
        Path(__file__).resolve().parents[2]
        / "collections"
        / "ansible_collections"
        / "internal"
        / "core"
        / "plugins"
        / "module_utils"
        / "report_aggregation.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "internal_core_report_aggregation", _helper_path
    )
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    load_all_reports = _mod.load_all_reports
    write_output = _mod.write_output
    _vmware_adapter_path = (
        Path(__file__).resolve().parents[2]
        / "collections"
        / "ansible_collections"
        / "internal"
        / "vmware"
        / "plugins"
        / "module_utils"
        / "report_aggregation_adapter.py"
    )
    if _vmware_adapter_path.exists():
        _vmw_spec = importlib.util.spec_from_file_location(
            "internal_vmware_report_aggregation_adapter", _vmware_adapter_path
        )
        _vmw_mod = importlib.util.module_from_spec(_vmw_spec)
        assert _vmw_spec is not None and _vmw_spec.loader is not None
        _vmw_spec.loader.exec_module(_vmw_mod)
        _vmware_report_normalizer = _vmw_mod.normalize_aggregated_report
    else:
        _vmware_report_normalizer = None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <report_dir> <output_path> [audit_type_filter]")
        sys.exit(1)

    all_data = load_all_reports(
        sys.argv[1],
        audit_filter=(sys.argv[3] if len(sys.argv) > 3 else None),
        normalizer=_vmware_report_normalizer,
    )
    write_output(
        all_data or {"metadata": {"fleet_stats": {"total_hosts": 0}}, "hosts": {}},
        sys.argv[2],
    )
