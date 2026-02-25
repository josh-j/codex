
import importlib.util
import sys
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.report_aggregation import (
        load_all_reports,
        write_output,
    )
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
    _spec = importlib.util.spec_from_file_location("internal_core_report_aggregation", _helper_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    load_all_reports = _mod.load_all_reports
    write_output = _mod.write_output


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <report_dir> <output_path> [audit_type_filter]")
        sys.exit(1)

    all_data = load_all_reports(
        sys.argv[1],
        audit_filter=(sys.argv[3] if len(sys.argv) > 3 else None),
    )
    write_output(
        all_data or {"metadata": {"fleet_stats": {"total_hosts": 0}}, "hosts": {}},
        sys.argv[2],
    )
