"""Re-export shim — canonical source is ncs_core.aggregation."""

from ncs_core.aggregation import (  # noqa: F401
    deep_merge,
    load_all_reports,
    read_report,
    write_output,
)

__all__ = [
    "deep_merge",
    "load_all_reports",
    "read_report",
    "write_output",
]
