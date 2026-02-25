"""Reusable reporting/alert primitives shared across collection plugins."""


def safe_list(value):
    if isinstance(value, str):
        return []
    try:
        return list(value or [])
    except (TypeError, ValueError):
        return []


def as_list(value):
    return safe_list(value)


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_detail(detail):
    if isinstance(detail, dict):
        return detail
    if detail is None:
        return {}
    return {"value": detail}


def build_alert(severity, category, message, detail=None, affected_items=None, **extra):
    out = {
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


def canonical_severity(value):
    sev = str(value or "INFO").upper()
    if sev in ("CRITICAL", "CAT_I", "HIGH", "SEVERE", "FAILED"):
        return "CRITICAL"
    if sev in ("WARNING", "WARN", "CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
    return "INFO"


def threshold_severity(value, critical_pct, warning_pct):
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
    value,
    critical_pct,
    warning_pct,
    category,
    message,
    detail=None,
    direction="gt",
    value_key="usage_pct",
    affected_items=None,
    **extra,
):
    """
    Build a threshold-based alert dict or return None.

    direction:
      - "gt": fire when value > thresholds (critical first)
      - "le": fire when value <= thresholds (critical first)
    """
    value_f = to_float(value, 0.0)
    crit_f = to_float(critical_pct, 0.0)
    warn_f = to_float(warning_pct, 0.0)

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
    count,
    severity,
    category,
    message,
    detail=None,
    count_key="count",
    min_count=1,
    affected_items=None,
    **extra,
):
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
