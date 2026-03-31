"""Reusable reporting/alert primitives shared across collection plugins."""

from typing import Any, TypeVar

T = TypeVar("T")


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return []
    try:
        return list(value or [])
    except (TypeError, ValueError):
        return []


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def canonical_severity(value: Any) -> str:
    from .constants import (
        CRITICAL_ALIASES, INFO_ALIASES, SEVERITY_CRITICAL, SEVERITY_INFO,
        SEVERITY_WARNING, WARNING_ALIASES,
    )
    sev = str(value or "INFO").upper().replace(" ", "_")
    if sev in CRITICAL_ALIASES:
        return SEVERITY_CRITICAL
    if sev in WARNING_ALIASES:
        return SEVERITY_WARNING
    if sev in INFO_ALIASES:
        return SEVERITY_INFO
    return SEVERITY_INFO


SECONDS_PER_DAY: int = 86400
BYTES_PER_GB: float = 1024.0**3
BYTES_PER_MB: float = 1024.0**2


def canonical_stig_status(value: Any) -> str:
    """Unified STIG status canonicalization (superset of all platform mappings)."""
    from .constants import (
        STIG_NA_ALIASES, STIG_NOT_REVIEWED_ALIASES, STIG_OPEN_ALIASES,
        STIG_PASS_ALIASES, STIG_STATUS_NA, STIG_STATUS_NOT_REVIEWED,
        STIG_STATUS_OPEN, STIG_STATUS_PASS,
    )
    text = str(value or "").strip().lower()
    if text in STIG_OPEN_ALIASES:
        return STIG_STATUS_OPEN
    if text in STIG_PASS_ALIASES:
        return STIG_STATUS_PASS
    if text in STIG_NA_ALIASES:
        return STIG_STATUS_NA
    if text in STIG_NOT_REVIEWED_ALIASES:
        return STIG_STATUS_NOT_REVIEWED
    if text in ("error", "unknown"):
        return text
    return text or ""


__all__ = [
    "BYTES_PER_GB",
    "BYTES_PER_MB",
    "SECONDS_PER_DAY",
    "T",
    "canonical_severity",
    "canonical_stig_status",
    "safe_list",
    "to_float",
    "to_int",
]
