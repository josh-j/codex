from typing import Any, TypeVar

"""Reusable reporting/alert primitives shared across collection plugins."""

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


def build_alert(
    severity: str,
    category: str,
    message: str,
    detail: Any = None,
    affected_items: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "message": message,
        "detail": normalize_detail(detail),
    }
    if affected_items is not None:
        out["affected_items"] = affected_items
    for key, val in extra.items():
        if val is not None:
            out[key] = val
    return out


def canonical_severity(value: Any) -> str:
    sev = str(value or "INFO").upper()
    if sev in ("CRITICAL", "CAT_I", "HIGH", "SEVERE", "FAILED"):
        return "CRITICAL"
    if sev in ("WARNING", "WARN", "CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
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
