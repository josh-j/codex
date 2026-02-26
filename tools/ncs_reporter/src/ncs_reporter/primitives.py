"""Re-export shim — canonical source is ncs_core.primitives."""

from ncs_core.primitives import (  # noqa: F401
    T,
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
    "T",
    "as_list",
    "build_alert",
    "build_count_alert",
    "build_threshold_alert",
    "canonical_severity",
    "normalize_detail",
    "safe_list",
    "threshold_severity",
    "to_float",
    "to_int",
]
