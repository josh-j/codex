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


def as_list(value: Any) -> list[Any]:
    return safe_list(value)


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


def normalize_detail(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    if detail is None:
        return {}
    return {"value": detail}


def canonical_severity(value: Any) -> str:
    sev = str(value or "INFO").upper().replace(" ", "_")
    if sev in ("CRITICAL", "CAT_I", "HIGH", "SEVERE", "FAILED"):
        return "CRITICAL"
    if sev in ("WARNING", "WARN", "CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
    if sev in ("CAT_III", "LOW"):
        return "INFO"
    return "INFO"


def threshold_severity(value: Any, critical_pct: Any, warning_pct: Any) -> tuple[str | None, float | None]:
    """
    Return (severity, threshold) for a value crossing critical/warning thresholds.
    Critical takes precedence. Returns (None, None) if no threshold is crossed.
    """
    value_f = to_float(value, 0.0)
    crit_f = to_float(critical_pct, 0.0)
    warn_f = to_float(warning_pct, 0.0)

    if value_f > crit_f:
        return "CRITICAL", crit_f
    if value_f > warn_f:
        return "WARNING", warn_f
    return None, None


def build_alert(
    severity: str,
    category: str,
    message: str,
    detail: Any = None,
    affected_items: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    sl = safe_list(affected_items)

    out: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "message": message,
        "detail": normalize_detail(detail),
        "affected_items": sl,
    }

    for key, val in extra.items():
        if val is not None:
            out[key] = val
    return out


def build_threshold_alert(
    value: Any,
    critical_pct: Any,
    warning_pct: Any,
    category: str,
    message: str,
    detail: Any = None,
    direction: str = "gt",
    value_key: str = "usage_pct",
    affected_items: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any] | None:
    """
    Build a threshold-based alert dict or return None.

    direction:
      - "gt": fire when value > thresholds (critical first)
      - "le": fire when value <= thresholds (critical first)
    """
    value_f = to_float(value, 0.0)
    crit_f = to_float(critical_pct, 0.0)
    warn_f = to_float(warning_pct, 0.0)

    severity: str | None
    threshold: float | None

    if direction == "le":
        if value_f <= crit_f:
            severity, threshold = "CRITICAL", crit_f
        elif value_f <= warn_f:
            severity, threshold = "WARNING", warn_f
        else:
            return None
    else:
        severity, threshold = threshold_severity(value_f, crit_f, warn_f)
        if severity is None:
            return None

    payload_detail = normalize_detail(detail)
    payload_detail.setdefault(value_key, value_f)
    payload_detail["threshold_pct"] = threshold

    return build_alert(
        severity,
        category,
        message,
        payload_detail,
        affected_items=affected_items,
        **extra,
    )


def build_count_alert(
    count: Any,
    severity: str,
    category: str,
    message: str,
    detail: Any = None,
    count_key: str = "count",
    min_count: Any = 1,
    affected_items: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any] | None:
    """
    Build an alert when count >= min_count, injecting the count into detail.
    Returns None if count is below the threshold.
    """
    count_i = to_int(count, 0)
    if count_i < to_int(min_count, 1):
        return None

    payload_detail = normalize_detail(detail)
    payload_detail.setdefault(count_key, count_i)

    return build_alert(
        severity,
        category,
        message,
        payload_detail,
        affected_items=affected_items,
        **extra,
    )


SECONDS_PER_DAY: int = 86400
BYTES_PER_GB: float = 1024.0**3
BYTES_PER_MB: float = 1024.0**2


def canonical_stig_status(value: Any) -> str:
    """Unified STIG status canonicalization (superset of all platform mappings)."""
    text = str(value or "").strip().lower()
    if text in ("failed", "fail", "open", "finding", "non-compliant", "non_compliant"):
        return "open"
    if text in ("pass", "passed", "compliant", "success", "fixed", "remediated",
                "closed", "notafinding", "not_a_finding"):
        return "pass"
    if text in ("na", "n/a", "not_applicable", "not applicable", "not_applicable"):
        return "na"
    if text in ("not_reviewed", "not reviewed", "unreviewed"):
        return "not_reviewed"
    if text in ("error", "unknown"):
        return text
    return text or ""


__all__ = [
    "BYTES_PER_GB",
    "BYTES_PER_MB",
    "SECONDS_PER_DAY",
    "T",
    "as_list",
    "build_alert",
    "build_count_alert",
    "build_threshold_alert",
    "canonical_severity",
    "canonical_stig_status",
    "normalize_detail",
    "safe_list",
    "threshold_severity",
    "to_float",
    "to_int",
]
