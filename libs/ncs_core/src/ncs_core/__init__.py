"""Shared primitives and aggregation helpers for NCS."""

from ncs_core.aggregation import (
    deep_merge,
    load_all_reports,
    read_report,
    write_output,
)
from ncs_core.primitives import (
    as_list,
    build_alert,
    build_count_alert,
    build_threshold_alert,
    canonical_severity,
    normalize_detail,
    safe_list,
    threshold_severity,
    to_float,
    to_int,
)

__all__ = [
    "as_list",
    "build_alert",
    "build_count_alert",
    "build_threshold_alert",
    "canonical_severity",
    "deep_merge",
    "load_all_reports",
    "normalize_detail",
    "read_report",
    "safe_list",
    "threshold_severity",
    "to_float",
    "to_int",
    "write_output",
]
